"""The nes adapter: NES game memory to semantic facts, for choosing the next move in a platformer.

Ships one game mapping: Nova the Squirrel (v1.0.6a), an open-source NES platformer by NovaSquirrel
(code GPL-3.0-or-later, assets CC BY-NC-SA 4.0). jevbrief never ships or downloads the ROM.
Addresses come from the game's source (src/memory.s) and were checked on the official release.

`extract()` takes a snapshot, not an emulator, so any emulator works:
    {"ram": 2048 bytes ($0000-$07FF), "map": 4096 bytes ($6000-$6FFF), "flags": 256 bytes ($7000-$70FF),
     "frame": optional 240x256 RGB frame (numpy array or bytes)}
or the path of a snapshot saved with `save_snapshot`. `jevbrief.adapters.nes.game.NovaGame` makes
snapshots with the `cynes` emulator (`pip install "jevbrief[nes]"`).

Positions, distances, and heights are turned into words here. Jev never sees raw numbers.
"""

from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import Path

from ...briefing import Extracted
from ...facts import Fact, clean_label, fact_id, register_reasons
from ...questions import OptionChoice
from ...rules import CORE_RULES, Boost, Drop, Rule, RuleSet
from .. import Adapter

INACTIVE = "nes.inactive"
EFFECT = "nes.effect"
OFFSCREEN = "nes.offscreen"
BEHIND = "nes.behind_player"
FAR = "nes.far_ahead"
REASONS = {
    INACTIVE: "Empty object slot: nothing is there",
    EFFECT: "A visual effect or the player's own shot, not something to react to",
    OFFSCREEN: "Outside the visible screen",
    BEHIND: "Already passed: behind the player and not touching",
    FAR: "Too far ahead to matter for the next move",
    "nes.threat": "Kept: an enemy close ahead at the player's height",
    "nes.in_path": "Kept: a wall, pit, or hazard in the player's path",
    "nes.player": "Kept: the player",
}

# Nova the Squirrel RAM map (zero page and internal RAM).
SCROLL_X = 0x1F         # 2 bytes: fraction, block
PLAYER_X = 0x25         # fraction, block (x is the sprite's center)
PLAYER_Y = 0x27         # block, fraction (y is the sprite's top)
OBJ_TYPE = 0x2D         # 16 slots, type * 2 + direction
PLAYER_JUMPING = 0x45
PLAYER_ON_GROUND = 0x46
PLAYER_HEALTH = 0x4B    # half hearts
LEVEL_NUMBER = 0xA7
OBJ_XH, OBJ_XL, OBJ_YH, OBJ_YL = 0x3E3, 0x3F3, 0x403, 0x413
SLOTS = 16
MAX_HEALTH = 4
PLAYER_W, PLAYER_H, OBJ_W, OBJ_H = 16, 24, 16, 16
SCREEN_W, SCREEN_H = 256, 240
ROWS = 16               # the level map is column-major, 16 blocks per column
SCAN_COLUMNS = 12       # how far ahead the terrain is read, in blocks

# Metatile flags ($7000 + block id): solid on all sides, solid on top only, behavior in the low bits.
SOLID_ALL, SOLID_TOP, BEHAVIOR = 0x80, 0x40, 0x1F
HAZARDS = {6: "spikes", 9: "lava"}

# Object type names, in the order of the game's object list.
NAMES = ("none goomba sneaker spinner owl king toastbot ball potion george big_george alan ice ice ball_guy "
         "thwomp cannon cannon burger fire_walk fire_jump mine rocket rocket_launcher firework_shooter tornado "
         "electric_fan cloud bouncer gremlin rover turkey bomb_guy poof player_projectile blaster_shot "
         "faceball_shot boomerang fireball flames water_bottle ice_block ronald ronald_burger fries fry sun "
         "sun_key moving_platform moving_platform firebar boss_fight scheme_team flying_arrow falling_bomb "
         "boulder checkpoint big_glider big_lwss explosion minecart boomerang_guy grabby_hand falling_spike "
         "cloud_sword firework_shot collectible molsno molsno_note buddy beam_emitter laser_beam "
         "forehead_block_guy forehead_block fighter_maker moving_platform dropped_bomb_guy john john_ice").split()
EFFECTS = {"poof", "player_projectile", "explosion"}
PLATFORMS = {"moving_platform", "cloud", "minecart"}
ITEMS = {"potion", "sun_key", "checkpoint", "collectible", "water_bottle", "ice_block"}

# The platformer pack's actions. Buttons use cynes bits: A 128, B 64, Right 1, Left 2.
ACTIONS = {
    "run_right": ("Walk right for a moment. Safe when nothing is close ahead.", 1, 12),
    "jump_right": ("A full running jump to the right: clears tall walls, wide pits, and enemies at Nova's height.", 129, 24),
    "short_hop": ("A small hop to the right: clears a low wall one block high, or a narrow pit.", 129, 6),
    "wait": ("Stand still for a moment, for example to let an enemy move away.", 0, 12),
    "run_left": ("Walk left for a moment, back away from danger.", 2, 12),
    "drop_down": ("Hold down to drop through a thin ledge to the path below. Only works when `player.standing_on` "
                  "is a thin ledge.", 4, 20),
}
LEDGE = 1  # block behavior: a thin ledge you can drop through


def _name(t: int) -> str:
    return NAMES[t] if t < len(NAMES) else f"object {t}"


def _kind(name: str) -> str:
    return ("effect" if name in EFFECTS else "platform" if name in PLATFORMS else
            "item" if name in ITEMS else "enemy")


def distance(blocks: float) -> str:
    """Horizontal gap in blocks (16 pixels), as a word."""
    d = abs(blocks)
    return "touching" if d < 1 else "close" if d < 3 else "near" if d < 7 else "far"


def height(dy_px: float) -> str:
    """Vertical offset of a thing's bottom from the player's feet, in pixels (negative is higher)."""
    return "same height" if abs(dy_px) < 12 else "above" if dy_px < 0 else "below"


def health(h: int) -> str:
    return "full" if h >= MAX_HEALTH else "one hit left" if h <= 1 else "hurt"


def png(frame, width: int = SCREEN_W, height_: int = SCREEN_H) -> bytes:
    """Encode an RGB frame (numpy array or bytes) as PNG with the standard library."""
    data = frame.tobytes() if hasattr(frame, "tobytes") else bytes(frame)
    row = width * 3
    raw = b"".join(b"\0" + data[y * row:(y + 1) * row] for y in range(height_))

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height_, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def save_snapshot(path, snap: dict) -> None:
    """Save the RAM parts of a snapshot as small JSON (for tests and bug reports). The frame is not saved."""
    enc = {k: base64.b64encode(zlib.compress(bytes(snap[k]), 9)).decode() for k in ("ram", "map", "flags")}
    Path(path).write_text(json.dumps(enc), encoding="utf-8")


def load_snapshot(path) -> dict:
    enc = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: zlib.decompress(base64.b64decode(v)) for k, v in enc.items()}


def _pos(hi: int, lo: int) -> float:
    """Block plus fraction, in pixels."""
    return hi * 16 + lo / 16


def terrain(snap: dict, px: float, feet_px: float) -> list[dict]:
    """Walls, pits, and hazards in the columns ahead of the player. Numbers stay here, in code."""
    level, flags = snap["map"], snap["flags"]
    col0 = int(px // 16)
    feet = min(int(feet_px // 16), ROWS - 1)  # the row the player stands on

    def flag(c, r):
        return flags[level[c * ROWS + r]] if 0 <= c < len(level) // ROWS and 0 <= r < ROWS else 0

    out, c = [], col0 + 1
    while c <= col0 + SCAN_COLUMNS:
        body = flag(c, feet - 1)
        if body & SOLID_ALL:
            h = 0
            while h < feet and flag(c, feet - 1 - h) & SOLID_ALL:
                h += 1
            out.append({"kind": "wall", "col": c, "rows": h})
            c += 1
            while c <= col0 + SCAN_COLUMNS and flag(c, feet - 1) & SOLID_ALL:
                c += 1
            continue
        if not any(flag(c, r) & (SOLID_ALL | SOLID_TOP) for r in range(feet, ROWS)):
            w = 1
            while not any(flag(c + w, r) & (SOLID_ALL | SOLID_TOP) for r in range(feet, ROWS)) and w < 8:
                w += 1
            out.append({"kind": "pit", "col": c, "rows": w})
            c += w
            continue
        hazard = HAZARDS.get(flag(c, feet) & BEHAVIOR) or HAZARDS.get(body & BEHAVIOR)
        if hazard:
            out.append({"kind": hazard, "col": c, "rows": 1})
        c += 1
    return out


class NesAdapter(Adapter):
    name = "nes"
    version = "1"
    renderer = "spatial"
    extra = "nes"
    reasons = REASONS

    def __init__(self):
        register_reasons(REASONS)

    def extract(self, source, **options) -> Extracted:
        """Options: `last_action` (an action name) and `moved` (bool), so Jev knows when a move had no effect."""
        snap = load_snapshot(source) if isinstance(source, (str, Path)) else source
        ram = snap["ram"]
        scroll = _pos(ram[SCROLL_X + 1], ram[SCROLL_X])
        px, py = _pos(ram[PLAYER_X + 1], ram[PLAYER_X]), _pos(ram[PLAYER_Y], ram[PLAYER_Y + 1])
        feet = py + PLAYER_H
        on_ground = bool(ram[PLAYER_ON_GROUND])
        col, row = int(px // 16), min(int(feet // 16), ROWS - 1)
        under = snap["flags"][snap["map"][col * ROWS + row]] if col * ROWS + row < len(snap["map"]) else 0
        floor = "a thin ledge she can drop through" if on_ground and under & BEHAVIOR == LEDGE else "solid ground"

        def box(x, y, w, h):
            return [round(x - scroll - w / 2), round(y), w, h]

        facts = [Fact(id=fact_id("nes", "player"), kind="player", label="Nova (you)",
                      attrs={"state": "on the ground" if on_ground else "in the air",
                             "standing_on": floor if on_ground else "nothing",
                             "health": health(ram[PLAYER_HEALTH]),
                             **({"last_action": f"{options['last_action']}, "
                                                + ("she moved" if options.get("moved", True) else "nothing changed")}
                                if options.get("last_action") else {})},
                      meta={"box": box(px, py, PLAYER_W, PLAYER_H), "order": 0,
                            "raw": {"x": round(px), "y": round(py), "on_ground": ram[PLAYER_ON_GROUND],
                                    "jumping": ram[PLAYER_JUMPING], "health": ram[PLAYER_HEALTH],
                                    "scroll_x": round(scroll), "last_action": options.get("last_action"),
                                    "moved": options.get("moved", True)},
                            "columns": [(c, list(snap["map"][c * ROWS:(c + 1) * ROWS]))
                                        for c in range(int(px // 16), int(px // 16) + SCAN_COLUMNS + 1)
                                        if c * ROWS < len(snap["map"])]})]

        for i in range(SLOTS):
            t = ram[OBJ_TYPE + i] >> 1
            name = _name(t)
            ox, oy = _pos(ram[OBJ_XH + i], ram[OBJ_XL + i]), _pos(ram[OBJ_YH + i], ram[OBJ_YL + i])
            dx = (ox - px) / 16
            side = "ahead" if dx >= 0 else "behind"
            words = {"side": side, "distance": distance(dx), "height": height(oy + OBJ_H - feet)}
            label = name.replace("_", " ").capitalize()
            sx = ox - scroll
            facts.append(Fact(
                id=fact_id("nes", "slot", str(i)),
                kind=_kind(name) if t else "empty",
                label=clean_label(f"{label}: {words['side']}, {words['distance']}, {words['height']}") if t else f"Empty slot {i}",
                attrs=words if t else {},
                meta={"type": t, "dx": round(dx, 2), "onscreen": -OBJ_W < sx < SCREEN_W + OBJ_W,
                      "raw": {"type_id": t, "x": round(ox), "y": round(oy), "flags": ram[OBJ_TYPE + i]},
                      "box": box(ox, oy, OBJ_W, OBJ_H) if t else None, "order": 1 + i},
            ))

        for k, th in enumerate(terrain(snap, px, feet)):
            dx = (th["col"] * 16 - px) / 16
            if th["kind"] == "wall":
                size = "low (one block)" if th["rows"] == 1 else "tall" if th["rows"] <= 3 else "very tall"
                label, attrs = f"Wall ahead, {size}", {"height": size}
            elif th["kind"] == "pit":
                size = "narrow" if th["rows"] <= 2 else "wide"
                label, attrs = f"Pit ahead, {size}", {"width": size}
            else:
                label, attrs = f"{th['kind'].capitalize()} ahead", {}
            attrs = {"side": "ahead", "distance": distance(dx), **attrs}
            top = (int(feet // 16) - th["rows"]) * 16 if th["kind"] == "wall" else int(feet // 16) * 16
            facts.append(Fact(
                id=fact_id("nes", th["kind"], str(th["col"])), kind=th["kind"] if th["kind"] in ("wall", "pit") else "hazard",
                label=clean_label(f"{label}, {attrs['distance']}"), attrs=attrs,
                meta={"dx": round(dx, 2), "onscreen": True, "order": 20 + k,
                      "box": [round(th["col"] * 16 - scroll), top, 16 * (th["rows"] if th["kind"] == "pit" else 1),
                              16 * (th["rows"] if th["kind"] == "wall" else 1)]},
            ))

        source = {"name": f"Nova the Squirrel, level {ram[LEVEL_NUMBER] + 1}",
                  "health": health(ram[PLAYER_HEALTH]), "on_ground": on_ground}
        image = png(snap["frame"]) if snap.get("frame") is not None else None
        return Extracted(facts, source, image=image, image_size=(SCREEN_W, SCREEN_H) if image else None)

    def rules(self) -> RuleSet:
        hidden, disabled, unlabeled, goal_match, duplicate = CORE_RULES

        def threat(f, ctx):
            a = f.attrs
            return (f.kind == "enemy" and a.get("side") == "ahead" and a.get("distance") in ("touching", "close")
                    and a.get("height") == "same height")

        return RuleSet([
            Rule(INACTIVE, lambda f, ctx: Drop(INACTIVE) if f.kind == "empty" else None),
            Rule("nes.player", lambda f, ctx: Boost(0.5, "nes.player") if f.kind == "player" else None),
            hidden, disabled, unlabeled,
            Rule(EFFECT, lambda f, ctx: Drop(EFFECT) if f.kind == "effect" else None),
            Rule(OFFSCREEN, lambda f, ctx: Drop(OFFSCREEN) if not f.meta.get("onscreen", True) else None),
            Rule(BEHIND, lambda f, ctx: Drop(BEHIND) if f.meta.get("dx", 0) <= -1 else None),
            Rule(FAR, lambda f, ctx: Drop(FAR) if f.attrs.get("distance") == "far" else None),
            goal_match,
            Rule("nes.threat", lambda f, ctx: Boost(0.3, "nes.threat") if threat(f, ctx) else None),
            Rule("nes.in_path", lambda f, ctx: Boost(0.2, "nes.in_path")
                 if f.kind in ("wall", "pit", "hazard") and f.attrs.get("distance") in ("touching", "close") else None),
            duplicate,
        ])

    def packs(self):
        pack = OptionChoice(
            "next_action",
            "Goal: {goal}\n`player` is Nova, a squirrel in a side-scrolling platformer, moving right toward the "
            "level's end. `nearby` lists what is around her, already described in words. Touching an enemy, "
            "spikes, or lava hurts her; falling into a pit loses a life. Which one action should she take now?",
            {k: v[0] for k, v in ACTIONS.items()},
            extra={"danger": {"type": "noul", "instructions":
                              "If Nova keeps walking right for the next half second, will she touch an enemy, "
                              "spikes, or lava, or fall into a pit?"}},
        )
        return {"platformer": pack}

    def state(self, goal, kept, source):
        player = next((f.attrs for f in kept if f.kind == "player"), {})
        return {"goal": goal, "player": player, "nearby": [f.state() for f in kept if f.kind != "player"]}

    def raw(self, facts):
        """What a naive integration sends: every object slot and nearby column with raw numbers."""
        out = []
        for f in facts:
            if f.kind == "player":
                out.append(Fact(id=f.id, kind="player", label="player", attrs=f.meta["raw"], meta=f.meta))
                out += [Fact(id=fact_id("nes-raw", "col", str(c)), kind="column", label=f"level column {c}",
                             attrs={"column": c, "block_ids": ids}, meta={"order": 40 + c})
                        for c, ids in f.meta["columns"]]
            elif "raw" in f.meta:
                out.append(Fact(id=f.id, kind="object", label=f"object slot {f.meta['order'] - 1}",
                                attrs=f.meta["raw"], meta=f.meta))
        return out
