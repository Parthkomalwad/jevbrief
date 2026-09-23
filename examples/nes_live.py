"""Jev plays Nova the Squirrel, level 1-1, and you watch it live in the jevbrief viewer.

    pip install "jevbrief[nes]"
    python examples/nes_live.py --rom path/to/nova.nes --headed

Get the free ROM from the author's release page (v1.0.6a):
https://github.com/NovaSquirrel/NovaTheSquirrel/releases/tag/v1.0.6a
Needs TYPESAFE_API_KEY in the environment or a .env file.

Each decision: read the game's memory, turn it into a few facts in words, ask Jev which action to take
(and, in the same call, whether walking right is dangerous), then hold that action for a moment.
The emulator is paused while Jev answers.
"""

import argparse
import os
import sys
from pathlib import Path

from typesafe_sdk import TypeSafeClient

from jevbrief import Briefing
from jevbrief.adapters.nes import NesAdapter
from jevbrief.adapters.nes.game import NovaGame, play
from jevbrief.cli import load_env
from jevbrief.jev import DEFAULT_MODEL, Jev
from jevbrief.viewer import serve_live

GOAL = "Get Nova to the end of the level without getting hurt"


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--rom", required=True, help="Path to your nova.nes (v1.0.6a)")
    p.add_argument("--headed", action="store_true", help="Open the live viewer in your browser")
    p.add_argument("--decisions", type=int, default=150)
    p.add_argument("--trace", default="traces/nes.jsonl")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--danger", type=float, default=0.7, help="Wait instead of walking right above this danger")
    p.add_argument("--timeout", type=float, default=3.0,
                   help="Seconds before a Jev call is retried (default 3). A hung call then costs one move, not 10+ s")
    a = p.parse_args()

    load_env()
    if not os.environ.get("TYPESAFE_API_KEY"):
        sys.exit("TYPESAFE_API_KEY is not set. Add it to your environment or a .env file.")

    trace = Path(a.trace)
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.unlink(missing_ok=True)
    game = NovaGame(a.rom, live_frame=trace.with_suffix(".live.png"))
    game.start_level()
    server = serve_live(trace, port=a.port, open_browser=a.headed)
    print(f"live viewer: http://127.0.0.1:{server.server_port}/")

    jev = Jev(client=TypeSafeClient(model=DEFAULT_MODEL, timeout=a.timeout))
    b = Briefing(NesAdapter(), GOAL, trace=str(trace), jev=jev)
    result = play(game, b, a.decisions, a.danger)
    print(result)
    print(f"trace: {trace}   replay it any time: jevbrief view {trace}")
    if a.headed:
        input("Press Enter to stop the live viewer.")
    server.shutdown()


if __name__ == "__main__":
    main()
