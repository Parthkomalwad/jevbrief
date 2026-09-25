"""Find why a CI build failed, and whether it looks flaky.

Run:  python examples/ci_failure.py examples/data/ci_run.log "CI is red on main"
Your own run:  gh run view <run id> --log-failed > run.log   (or download the run's log archive zip)
Needs TYPESAFE_API_KEY in the environment or in a .env file.
"""

import sys

from jevbrief import Briefing
from jevbrief.adapters.ci import CiAdapter
from jevbrief.cli import load_env


def main() -> None:
    load_env()
    path = sys.argv[1] if len(sys.argv) > 1 else "examples/data/ci_run.log"
    goal = " ".join(sys.argv[2:]) or "CI is red on main"
    brief = Briefing(CiAdapter(), goal, trace="traces/ci.jsonl")
    brief.extract(path)
    print(f"{brief.source['lines']} log lines -> {len(brief.facts)} failures -> {len(brief.kept)} sent to Jev")
    decision = brief.decide()
    if decision.fact:
        f = decision.fact
        print(f"likely cause: {f.label}\n  {f.attrs}\n  confidence {decision.confidence:.2f}")
    else:
        print(f"no clear cause: {decision.outcome}")
    flaky = (decision.answers.get("flaky") or {}).get("noul")
    if flaky is not None:
        print(f"looks flaky: {'yes' if flaky > 0.5 else 'no'} ({flaky:.2f})")
    print("see it: jevbrief view traces/ci.jsonl")


if __name__ == "__main__":
    main()
