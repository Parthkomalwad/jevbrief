"""Find the likely cause of an incident in an OpenTelemetry log export.

Run:  python examples/otel_incident.py bench/otel/checkout_500.json "Checkout requests started failing with 500 errors"
Needs TYPESAFE_API_KEY in the environment or in a .env file.
"""

import sys

from jevbrief import Briefing
from jevbrief.adapters.otel import OtelAdapter
from jevbrief.cli import load_env


def main() -> None:
    load_env()
    path = sys.argv[1] if len(sys.argv) > 1 else "bench/otel/checkout_500.json"
    goal = " ".join(sys.argv[2:]) or "Checkout requests started failing with 500 errors"
    brief = Briefing(OtelAdapter(), goal, trace="traces/incident.jsonl")
    brief.extract(path)
    print(f"{brief.source['records']} log records -> {len(brief.facts)} groups -> {len(brief.kept)} sent to Jev")
    decision = brief.decide()
    if decision.fact:
        f = decision.fact
        print(f"likely cause: {f.label}\n  {f.attrs}\n  confidence {decision.confidence:.2f}")
    else:
        print(f"no clear cause: {decision.outcome}")
    print("see it: jevbrief view traces/incident.jsonl")


if __name__ == "__main__":
    main()
