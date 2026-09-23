from jevbrief import trace
from jevbrief.facts import Fact


def test_trace_round_trips_through_jsonl(tmp_path):
    fact = Fact(id="e14", kind="button", label="Add to cart", score=0.92, reason="goal_match")
    rec = trace.TraceRecord(
        run_id="r_8f2c",
        tick=3,
        source={"adapter": "dom", "url": "https://example.com/product", "raw_facts": 212},
        goal="add this item to the cart",
        facts=[fact.to_dict("summary")],
        budget={"limit_tokens": 2000, "used_tokens": 640, "cut_for_budget": 0},
        fingerprint={"hash": "a91c", "changed": True, "reused_tick": None},
        jev={"model": "jev-1.13.0", "question": "next_click", "choice": "e14", "confidence": 0.88,
             "probabilities": {"e14": 0.88}, "latency_ms": 212},
        outcome="applied",
    )
    path = tmp_path / "t.jsonl"
    trace.write(path, rec)
    trace.write(path, rec)
    back = trace.read(path)
    assert len(back) == 2
    assert back[0] == rec
    assert back[0].facts == [{"id": "e14", "kept": True, "reason": "goal_match"}]
