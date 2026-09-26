import json
import re
from pathlib import Path

from jevbrief import Briefing
from jevbrief.adapters.nes import (
    ACTIONS,
    OBJ_TYPE,
    OBJ_XH,
    OBJ_XL,
    OBJ_YH,
    OBJ_YL,
    PLAYER_X,
    PLAYER_Y,
    SCROLL_X,
    NesAdapter,
    distance,
    health,
    height,
    load_snapshot,
)
from jevbrief.testing import FakeJev, check_adapter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nes"
GOAL = "reach the end of the level"


def snap(name="owl_and_wall"):
    s = load_snapshot(FIXTURES / f"{name}.json")
    return {k: bytearray(v) for k, v in s.items()}


def px(s, base):
    return s["ram"][base + 1] * 16 + s["ram"][base] / 16


def put(s, slot, t, dx_blocks, dy_px=0):
    """Place object type `t` in `slot`, `dx_blocks` from the player, with its bottom `dy_px` below the player's feet."""
    x = px(s, PLAYER_X) + dx_blocks * 16
    y = s["ram"][PLAYER_Y] * 16 + s["ram"][PLAYER_Y + 1] / 16 + 24 - 16 + dy_px
    ram = s["ram"]
    ram[OBJ_TYPE + slot] = t << 1
    ram[OBJ_XH + slot], ram[OBJ_XL + slot] = int(x // 16), int(x % 16 * 16)
    ram[OBJ_YH + slot], ram[OBJ_YL + slot] = int(y // 16), int(y % 16 * 16)
    return s


def brief(s):
    b = Briefing(NesAdapter(), GOAL, trace=None, jev=FakeJev())
    b.extract(s)
    return b


def slot_fact(b, slot):
    return next(f for f in b.facts if f.meta.get("order") == 1 + slot)


def test_contract():
    check_adapter(NesAdapter(), FIXTURES / "owl_and_wall.json", goal=GOAL)


def test_extracts_recorded_snapshot_as_words():
    b = brief(snap())
    kept = {f.label for f in b.kept}
    assert kept == {"Nova (you)", "Owl: ahead, near, above", "Wall ahead, low (one block), touching"}
    state = b.state()
    assert state["player"] == {"state": "on the ground", "standing_on": "solid ground", "health": "full"}
    # Jev never sees raw numbers: no digits outside fact IDs.
    text = json.dumps([{k: v for k, v in f.items() if k != "id"} for f in state["nearby"]] + [state["player"]])
    assert not re.search(r"\d", text)


def test_start_snapshot_sees_the_sand_block():
    b = brief(snap("start"))
    assert [f.label for f in b.kept if f.kind == "wall"] == ["Wall ahead, tall, near"]


def test_words():
    assert [distance(d) for d in (0.5, -2, 5, 9)] == ["touching", "close", "near", "far"]
    assert [height(d) for d in (4, -30, 30)] == ["same height", "above", "below"]
    assert [health(h) for h in (4, 3, 1)] == ["full", "hurt", "one hit left"]


def test_inactive():
    empty = [f for f in brief(snap()).facts if f.kind == "empty"]
    assert empty and {f.reason for f in empty} == {"nes.inactive"}


def test_effect():
    b = brief(put(snap(), 0, 33, 2))  # a "poof" cloud
    assert slot_fact(b, 0).reason == "nes.effect"


def test_offscreen():
    s = put(snap(), 0, 1, 2)
    s["ram"][OBJ_XH] = (s["ram"][SCROLL_X + 1] + 40) % 256  # 40 blocks right of the screen's left edge
    assert slot_fact(brief(s), 0).reason == "nes.offscreen"


def test_behind_player():
    assert slot_fact(brief(put(snap(), 0, 1, -3)), 0).reason == "nes.behind_player"


def test_far_ahead():
    f = slot_fact(brief(put(snap(), 0, 1, 7.5)), 0)
    assert f.label.startswith("Goomba: ahead, far") and f.reason == "nes.far_ahead"


def test_threat():
    f = slot_fact(brief(put(snap(), 0, 1, 2)), 0)
    assert f.label == "Goomba: ahead, close, same height" and f.kept and f.reason == "nes.threat"


def test_in_path():
    wall = next(f for f in brief(snap()).facts if f.kind == "wall")
    assert wall.kept and wall.reason == "nes.in_path"


def test_player():
    player = next(f for f in brief(snap()).facts if f.kind == "player")
    assert player.kept and player.reason == "nes.player"


def test_pits_and_hazards_from_the_level_map():
    s = snap("start")
    col = int(px(s, PLAYER_X) // 16) + 2
    spikes = next(i for i in range(1, 256) if i not in s["map"])  # an unused block id, redefined as spikes
    s["flags"][spikes] = 0x80 | 0x40 | 6
    for c in (col, col + 1, col + 2):
        s["map"][c * 16:(c + 1) * 16] = bytes(16)  # empty column: a pit
    s["map"][(col + 3) * 16 + 13] = spikes
    labels = [f.label for f in brief(s).facts if f.kind in ("pit", "hazard")]
    assert labels == ["Pit ahead, wide, close", "Spikes ahead, near"]


def test_pack_asks_one_action_and_danger():
    b = brief(snap())
    qs = NesAdapter().packs()["platformer"].build(GOAL, b.kept, b.state())
    assert list(qs["next_action"]["criteria"]) == list(ACTIONS)
    assert qs["danger"]["type"] == "noul"


def test_raw_arm_sends_numbers():
    ex = NesAdapter().extract(snap())
    raw = NesAdapter().raw(ex.facts)
    kinds = {f.kind for f in raw}
    assert kinds == {"player", "object", "column"} and len([f for f in raw if f.kind == "object"]) == 16
    assert isinstance(next(f for f in raw if f.kind == "player").attrs["x"], int)


def test_frame_becomes_png_with_boxes():
    s = snap()
    s["frame"] = bytes(256 * 240 * 3)  # synthetic black frame
    ex = NesAdapter().extract(s)
    assert ex.image.startswith(b"\x89PNG") and ex.image_size == (256, 240)
    assert all(len(f.box) == 4 for f in ex.facts if f.kind in ("player", "wall"))


def test_thin_ledge_under_the_player():
    s = snap()
    col = int(px(s, PLAYER_X) // 16)
    row = int((s["ram"][PLAYER_Y] * 16 + s["ram"][PLAYER_Y + 1] / 16 + 24) // 16)
    s["flags"][s["map"][col * 16 + row]] = 0x40 | 1
    assert brief(s).state()["player"]["standing_on"] == "a thin ledge she can drop through"


def test_last_action_is_reported_in_words():
    b = Briefing(NesAdapter(), GOAL, trace=None, jev=FakeJev())
    b.extract(snap(), last_action="drop_down", moved=False)
    assert b.state()["player"]["last_action"] == "drop_down, nothing changed"
    raw = NesAdapter().raw(NesAdapter().extract(snap(), last_action="drop_down", moved=False).facts)
    assert raw[0].attrs["last_action"] == "drop_down" and raw[0].attrs["moved"] is False  # same feedback, raw form
