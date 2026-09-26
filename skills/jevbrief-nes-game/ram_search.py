"""Find a game's memory addresses by playing scripted inputs and watching which bytes change.

    python ram_search.py --rom game.nes --script "none*120,START*10,none*180" --save boot.state
    python ram_search.py --rom game.nes --load boot.state --script "RIGHT*90" --png after.png
    python ram_search.py --rom game.nes --load boot.state --script "A*20,none*40" --watch 0x86,0xce

Script: comma-separated `BUTTONS*frames`, buttons joined with `+` (A, B, SELECT, START, UP, DOWN, LEFT,
RIGHT) or `none`. Reports internal RAM ($0000-$07FF) and cartridge RAM ($6000-$7FFF) bytes that change,
grouped by how they moved: steadily up (x position, timers counting up), steadily down, or back and forth.
Needs `pip install "jevbrief[nes]"`. Uses only a ROM you are allowed to use.
"""

import argparse
from pathlib import Path

import numpy as np
from cynes import NES

BUTTONS = {"A": 128, "B": 64, "SELECT": 32, "START": 16, "UP": 8, "DOWN": 4, "LEFT": 2, "RIGHT": 1, "NONE": 0}
RANGES = [range(0x0000, 0x0800), range(0x6000, 0x8000)]


def parse(script: str):
    for step in script.split(","):
        names, _, frames = step.strip().partition("*")
        yield sum(BUTTONS[n.upper()] for n in names.split("+")), int(frames or 1)


def read(nes) -> np.ndarray:
    return np.array([nes[a] for r in RANGES for a in r], dtype=np.int16)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rom", required=True)
    p.add_argument("--script", required=True)
    p.add_argument("--load", help="start from a state saved with --save")
    p.add_argument("--save", help="save the state after the script")
    p.add_argument("--watch", help="comma-separated addresses to print every 10 frames")
    p.add_argument("--png", help="save the last frame as PNG, to look at the screen")
    p.add_argument("--every", type=int, default=5, help="sample RAM every N frames (default 5)")
    a = p.parse_args()

    nes = NES(a.rom)
    if a.load:
        nes.load(np.fromfile(a.load, dtype=np.uint8))
    addrs = [x for r in RANGES for x in r]
    watch = [int(x, 16) for x in a.watch.split(",")] if a.watch else []
    samples, frame, n = [read(nes)], None, 0
    for buttons, frames in parse(a.script):
        for _ in range(frames):
            nes.controller = buttons
            frame = nes.step(1)
            n += 1
            if n % a.every == 0:
                samples.append(read(nes))
            if watch and n % 10 == 0:
                print(f"frame {n:>5}: " + "  ".join(f"{w:#06x}={nes[w]:>3}" for w in watch))
    s = np.stack(samples)
    diff = np.diff(s, axis=0)
    changed = np.nonzero((s != s[0]).any(axis=0))[0]
    groups = {"steadily up": [], "steadily down": [], "back and forth": []}
    for i in changed:
        d = diff[:, i]
        key = "steadily up" if (d >= 0).all() else "steadily down" if (d <= 0).all() else "back and forth"
        groups[key].append(i)
    for name, idx in groups.items():
        print(f"\n{name} ({len(idx)} bytes)")
        for i in sorted(idx, key=lambda i: -np.abs(diff[:, i]).sum())[:40]:
            print(f"  {addrs[i]:#06x}  start {s[0, i]:>3}  end {s[-1, i]:>3}  min {s[:, i].min():>3}  max {s[:, i].max():>3}")
    if a.save:
        np.asarray(nes.save(), dtype=np.uint8).tofile(a.save)
    if a.png and frame is not None:
        from jevbrief.adapters.nes import png
        Path(a.png).write_bytes(png(frame))


if __name__ == "__main__":
    main()
