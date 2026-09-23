"""Check the Nova the Squirrel memory map against the real game, and record test snapshots.

    python bench/nes/verify_ram.py --rom path/to/nova.nes [--record tests/fixtures/nes]

Needs `pip install "jevbrief[nes]"` and the v1.0.6a release ROM (see docs/adapters/nes.md).
"""

import argparse
from pathlib import Path

from jevbrief.adapters.nes import OBJ_TYPE, NesAdapter, save_snapshot
from jevbrief.adapters.nes.game import NovaGame


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rom", required=True)
    p.add_argument("--record", help="folder to save RAM snapshots for the tests")
    a = p.parse_args()

    g = NovaGame(a.rom)
    g.start_level()
    x0 = g.x_blocks
    assert g.on_ground and g.health == 4, "level 1-1 should start on the ground with full health"
    snaps = {"start": g.snapshot()}

    for _ in range(4):
        g.hold("run_right")
    assert g.x_blocks > x0 + 2, "walking right should increase x"

    y_ground = g.y_blocks
    g._press(129, 6)
    assert not g.on_ground and g.y_blocks < y_ground, "pressing A should move Nova up, off the ground"
    g.hold("run_right")
    assert g.on_ground, "Nova should land again"

    for _ in range(12):
        g.hold("run_right")
    types = {g.peek(OBJ_TYPE + i) >> 1 for i in range(16)}
    assert 4 in types, f"the first owl should be in an object slot, got types {sorted(types)}"
    snaps["owl_and_wall"] = g.snapshot()

    facts = NesAdapter().extract(snaps["owl_and_wall"]).facts
    labels = [f.label for f in facts if f.label]
    assert any(label.startswith("Owl") for label in labels) and any(label.startswith("Wall") for label in labels), labels
    print("memory map OK:", labels)

    if a.record:
        Path(a.record).mkdir(parents=True, exist_ok=True)
        for name, snap in snaps.items():
            save_snapshot(Path(a.record) / f"{name}.json", snap)
        print("recorded", ", ".join(snaps), "to", a.record)


if __name__ == "__main__":
    main()
