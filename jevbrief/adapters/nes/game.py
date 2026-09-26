"""A thin wrapper around the cynes emulator for Nova the Squirrel. Needs `pip install "jevbrief[nes]"`.

The emulator only runs inside `hold()`, so it is paused while Jev answers.
"""

from __future__ import annotations

import contextlib
import hashlib
import warnings
from pathlib import Path

from .. import need
from . import ACTIONS, PLAYER_HEALTH, PLAYER_ON_GROUND, PLAYER_X, PLAYER_Y, png

RELEASE_SHA1 = "b6b07ee76492ed475f39167c89b342353f999231"  # nova.nes from the v1.0.6a GitHub release
RELEASE_URL = "https://github.com/NovaSquirrel/NovaTheSquirrel/releases/tag/v1.0.6a"
START, DOWN, A = 16, 4, 128


class NovaGame:
    def __init__(self, rom, live_frame=None):
        need("nes", "cynes")
        from cynes import NES

        data = Path(rom).read_bytes()
        if hashlib.sha1(data).hexdigest() != RELEASE_SHA1:
            warnings.warn(f"{rom} is not the Nova the Squirrel v1.0.6a release ({RELEASE_URL}); "
                          "the memory map may not match", stacklevel=2)
        self.nes = NES(str(rom))
        self.live_frame = Path(live_frame) if live_frame else None
        self.frame = None
        self.frames = 0
        self._press(0, 1)

    def _press(self, buttons: int, frames: int):
        for _ in range(frames):
            self.nes.controller = buttons
            self.frame = self.nes.step(1)
            self.frames += 1
            if self.live_frame and self.frames % 4 == 0:
                tmp = self.live_frame.with_suffix(".tmp")
                tmp.write_bytes(png(self.frame))
                with contextlib.suppress(PermissionError):  # Windows: the viewer is reading the old frame
                    tmp.replace(self.live_frame)

    def start_level(self):
        """From power-on: title screen, level select (level 1-1), then "Start!" in the level menu."""
        for _ in range(6):
            self._press(0, 40)
            self._press(START, 10)
        for buttons, frames in ((0, 60), (A, 10), (0, 60), (DOWN, 8), (0, 20), (A, 10), (0, 180)):
            self._press(buttons, frames)
        self.start = self.save()

    def save(self):
        return self.nes.save()

    def load(self, state):
        self.nes.load(state.copy())

    def peek(self, addr: int) -> int:
        return self.nes[addr]

    def snapshot(self) -> dict:
        n = self.nes
        return {"ram": bytes(n[a] for a in range(0x800)), "map": bytes(n[a] for a in range(0x6000, 0x7000)),
                "flags": bytes(n[a] for a in range(0x7000, 0x7100)), "frame": self.frame}

    @property
    def on_ground(self) -> bool:
        return bool(self.nes[PLAYER_ON_GROUND])

    @property
    def x_blocks(self) -> float:
        return self.nes[PLAYER_X + 1] + self.nes[PLAYER_X] / 256

    @property
    def y_blocks(self) -> float:
        return self.nes[PLAYER_Y] + self.nes[PLAYER_Y + 1] / 256

    @property
    def health(self) -> int:
        return self.nes[PLAYER_HEALTH]

    def hold(self, action: str, max_air_frames: int = 60) -> None:
        """Hold an action's buttons for its frames, then keep its direction until Nova lands."""
        _, buttons, frames = ACTIONS[action]
        self._press(buttons, frames)
        direction = buttons & 3
        for _ in range(max_air_frames):
            if self.on_ground:
                break
            self._press(direction, 1)


def choose(d, danger_threshold: float) -> str:
    """Jev's top action, even at low confidence (a wrong move in a game is cheap), or `wait` when the call
    failed or Jev says walking right is dangerous."""
    if d.outcome == "error" or d.choice not in ACTIONS:
        return "wait"
    danger = (d.answers.get("danger") or {}).get("noul")
    if d.choice == "run_right" and danger is not None and danger >= danger_threshold:
        return "wait"
    return d.choice


def play(game, briefing, decisions: int, danger_threshold: float = 0.7, log=print, load=None) -> dict:
    """Play for a fixed number of decisions. Returns the furthest x (blocks), hits taken, and deaths.

    `load(briefing, snapshot, **options)` puts a snapshot into the briefing (default: `briefing.extract`).
    """
    load = load or (lambda b, snap, **o: b.extract(snap, **o))
    best, hits, deaths, health = game.x_blocks, 0, 0, game.health
    action, moved = None, True
    for i in range(decisions):
        load(briefing, game.snapshot(), last_action=action, moved=moved)
        d = briefing.decide()
        action = choose(d, danger_threshold)
        before = (game.x_blocks, game.y_blocks)
        game.hold(action)
        moved = (game.x_blocks, game.y_blocks) != before
        if game.health < health:
            hits += health - game.health
        if game.health > health and game.x_blocks < before[0] - 3:  # respawned: full health, sent back
            deaths += 1
        health = game.health
        best = max(best, game.x_blocks)
        conf = f"{d.confidence:.2f}" if d.confidence is not None else "-"
        log(f"{i + 1:>3}  {d.outcome:<14} {d.choice!s:<10} {conf}  -> {action:<10} x={game.x_blocks:5.1f} health={game.health}")
    return {"furthest_x": round(best, 1), "hits": hits, "deaths": deaths}
