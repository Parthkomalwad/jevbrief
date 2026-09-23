"""NES benchmark: raw game memory against jevbrief facts, playing Nova the Squirrel level 1-1.

    python bench/nes/run.py --rom path/to/nova.nes [--decisions 100] [--repeats 3]

Both arms start from the same save state, use the same Jev model, questions, and action loop
(`jevbrief.adapters.nes.game.play`), and differ only in the state sent to Jev:
- raw: every object slot and the level columns ahead, with raw numbers (positions, type IDs, block IDs)
- jevbrief: the adapter's filtered facts, in words
Needs TYPESAFE_API_KEY. Traces go to traces/bench/nes/.
"""

import argparse
import json
import statistics
from pathlib import Path

from jevbrief import Briefing, budget
from jevbrief.adapters.nes import NesAdapter
from jevbrief.adapters.nes.game import NovaGame, play
from jevbrief.cli import load_env
from jevbrief.rules import RuleSet

GOAL = "Get Nova to the end of the level without getting hurt"
LEVEL_SIZE = 0x725D  # the level's last screen number; a screen is 16 blocks


def raw_load(adapter):
    def load(b, snap, **options):
        ex = adapter.extract(snap, **options)
        ex.facts = adapter.raw(ex.facts)
        b.load_extracted(ex)
        for f in b.facts:
            f.reason = "raw"
    return load


def briefing(arm, adapter, trace):
    if arm == "raw":
        return Briefing(adapter, GOAL, rules=RuleSet([], threshold=0), trace=trace,
                        max_options=budget.MAX_OPTIONS, budget_tokens=budget.MAX_TOKENS)
    return Briefing(adapter, GOAL, trace=trace)


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rom", required=True)
    p.add_argument("--decisions", type=int, default=100)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--out", default="traces/bench/nes")
    a = p.parse_args()
    load_env()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    game = NovaGame(a.rom)
    game.start_level()
    level_end = (game.peek(LEVEL_SIZE) + 1) * 16
    adapter = NesAdapter()
    runs = []
    for k in range(a.repeats):
        for arm in ("raw", "jevbrief"):
            trace = out / f"{arm}-{k + 1}.jsonl"
            trace.unlink(missing_ok=True)
            game.load(game.start)
            b = briefing(arm, adapter, str(trace))
            result = play(game, b, a.decisions, log=lambda s: None,
                          load=raw_load(adapter) if arm == "raw" else None)
            recs = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
            called = [r for r in recs if r["outcome"] != "reused"]
            run = {"arm": arm, "run": k + 1, **result, "completed": result["furthest_x"] >= level_end - 2,
                   "calls": len(called), "errors": sum(r["outcome"] == "error" for r in recs),
                   "tokens": med([r["jev"].get("input_tokens") for r in called]),
                   "latency": med([r["jev"].get("latency_ms") for r in called]),
                   "confidence": med([r["jev"].get("confidence") for r in called])}
            runs.append(run)
            print(json.dumps(run), flush=True)

    print(f"\nLevel 1-1 is {level_end} blocks long. {a.decisions} decisions per run.\n")
    print("| Arm | Furthest x (median, blocks) | Hits taken (total) | Deaths (total) | Completed | "
          "Jev calls (median) | Median input tokens | Median latency (ms) | Median confidence |")
    print("|---|---|---|---|---|---|---|---|---|")
    for arm in ("raw", "jevbrief"):
        r = [x for x in runs if x["arm"] == arm]
        print(f"| {arm} | {med([x['furthest_x'] for x in r])} | {sum(x['hits'] for x in r)} | "
              f"{sum(x['deaths'] for x in r)} | {sum(x['completed'] for x in r)}/{len(r)} | "
              f"{med([x['calls'] for x in r]):.0f} | {med([x['tokens'] for x in r]) or 0:.0f} | "
              f"{med([x['latency'] for x in r]) or 0:.0f} | {med([x['confidence'] for x in r]) or 0:.2f} |")
    print("\n| Run | Arm | Furthest x | Hits | Deaths | Calls | Errors |\n|---|---|---|---|---|---|---|")
    for x in runs:
        print(f"| {x['run']} | {x['arm']} | {x['furthest_x']} | {x['hits']} | {x['deaths']} | {x['calls']} | {x['errors']} |")


if __name__ == "__main__":
    main()
