"""Pick the next support ticket for a request, using the json adapter.

Run:  python examples/json_triage.py "a customer was billed twice this month"
Needs TYPESAFE_API_KEY in the environment or in a .env file.
"""

import sys
from pathlib import Path

from jevbrief import Briefing
from jevbrief.adapters.json import JsonAdapter
from jevbrief.cli import load_env

DATA = Path(__file__).resolve().parent.parent / "bench" / "json"


def main() -> None:
    load_env()
    goal = " ".join(sys.argv[1:]) or "a customer was billed twice this month"
    brief = Briefing(JsonAdapter(DATA / "tickets.toml"), goal, trace="traces/triage.jsonl")
    brief.extract(DATA / "tickets.json")
    print(f"{len(brief.facts)} tickets, {len(brief.kept)} sent to Jev")
    decision = brief.decide()
    if decision.fact:
        print(f"open {decision.fact.id}: {decision.fact.label!r} (confidence {decision.confidence:.2f})")
    else:
        print(f"no ticket chosen: {decision.outcome}")
    print("see it: jevbrief view traces/triage.jsonl")


if __name__ == "__main__":
    main()
