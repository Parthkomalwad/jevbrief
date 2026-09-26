"""The adapter contract. Every adapter, built-in or third-party, should pass `check_adapter`.

    from jevbrief.testing import check_adapter
    def test_my_adapter_contract():
        check_adapter(MyAdapter(), "tests/fixtures/sample.json", goal="find the refund ticket")

It runs the whole pipeline with a fake Jev (no API key, no network) and checks:
- facts have unique, stable IDs (the same across two extractions of the same source)
- every dropped fact has a registered reason code with a description
- adapter reason codes are namespaced as "<adapter>.<code>"
- the state is JSON-serializable and fits the token budget
- the question pack builds valid questions
- a decision writes a trace record that the viewer can render
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from . import budget
from .briefing import Briefing
from .facts import REASONS
from .jev import Answers


class FakeJev:
    """Answers every Choice with its first option and confidence 0.9. Never calls the network."""

    model = "fake"

    def ask(self, state, questions):
        answers = {}
        for qid, q in questions.items():
            if q["type"] == "choice":
                first = next(iter(q["criteria"]))
                answers[qid] = {"type": "choice", "choice": first, "confidence": 0.9, "probabilities": {first: 0.9}}
            elif q["type"] == "noul":
                answers[qid] = {"type": "noul", "noul": 0.5}
            else:
                answers[qid] = {"type": "score", "score": 0.0, "confidence": 0.9, "probabilities": {"0": 1.0}}
        return Answers("fake", answers, 1, 0)


def check_adapter(adapter, source, goal: str, **extract_options) -> Briefing:
    """Run the contract checks. Returns the Briefing so callers can add their own assertions."""
    from .viewer import render

    first = adapter.extract(source, **extract_options)
    second = adapter.extract(source, **extract_options)
    ids = [f.id for f in first.facts]
    assert first.facts, "extract() returned no facts"
    assert len(ids) == len(set(ids)), "fact IDs are not unique"
    assert ids == [f.id for f in second.facts], "fact IDs are not stable across extractions"

    for code in adapter.reasons:
        assert code.startswith(f"{adapter.name}."), f"reason code {code!r} must be namespaced as '{adapter.name}.<code>'"

    with tempfile.TemporaryDirectory() as tmp:
        trace_path = Path(tmp) / "t.jsonl"
        b = Briefing(adapter, goal, trace=str(trace_path), jev=FakeJev())
        b.load_extracted(first)
        for f in b.facts:
            assert REASONS.get(f.reason), f"reason {f.reason!r} is not registered with a description"

        state = b.state()
        json.dumps(state)
        assert budget.estimate_tokens(state) <= b.budget_tokens + 50, "state is over the token budget"

        for name, pack in adapter.packs().items():
            qs = pack.build(goal, b.kept, state)
            assert pack.primary in qs, f"pack {name!r} does not build its primary question {pack.primary!r}"
            for q in qs.values():
                assert q["type"] in ("choice", "noul", "score") and q.get("instructions")
                if q["type"] == "choice":
                    assert 1 <= len(q["criteria"]) <= 255, "a Choice needs 1 to 255 options"

        d = b.decide()
        assert d.record is not None and d.outcome in ("applied", "low_confidence")
        html = render(trace_path)
        assert "__TRACES__" not in html
    return b
