from jevbrief import trace
from jevbrief.facts import Fact


def record(**kw):
    fact = Fact(id="e14", kind="button", label="Add to cart", score=0.92, reason="goal_match")
    return trace.TraceRecord(
        run_id="r_8f2c", tick=3, adapter={"name": "web", "version": "1", "renderer": "spatial"},
        source={"url": "https://example.com/product", "raw_facts": 212}, goal="add this item to the cart",
        facts=[fact.to_dict("summary")], budget={"limit_tokens": 2000, "used_tokens": 640, "cut_for_budget": 0},
        fingerprint={"hash": "a91c", "changed": True, "reused_tick": None},
        jev={"model": "jev-1.13.0", "question": "next_click", "choice": "e14", "confidence": 0.88},
        outcome="applied", reasons={"goal_match": "Kept: matches the goal"}, **kw)


def test_trace_round_trips_through_jsonl(tmp_path):
    rec = record()
    path = tmp_path / "t.jsonl"
    trace.write(path, rec)
    trace.write(path, rec)
    back = trace.read(path)
    assert len(back) == 2 and back[0] == rec and back[0].schema == 1
    assert back[0].facts == [{"id": "e14", "kept": True, "reason": "goal_match"}]


def test_images_are_saved_next_to_the_trace(tmp_path):
    rec = record(image={"path": "", "width": 1280, "height": 800})
    path = tmp_path / "run.jsonl"
    trace.write(path, rec, image=b"\xff\xd8fake-jpeg")
    (back,) = trace.read(path)
    assert back.image["path"] == "run.assets/r_8f2c-3.jpg"
    assert (tmp_path / back.image["path"]).read_bytes() == b"\xff\xd8fake-jpeg"
    assert "fake-jpeg" not in path.read_text()


def test_read_ignores_unknown_fields(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text('{"run_id": "r", "tick": 1, "source": {}, "goal": "g", "facts": [], "budget": {}, '
                    '"fingerprint": {}, "jev": {}, "outcome": "applied", "page": {"image": "x"}, "future": 1}\n')
    (r,) = trace.read(path)
    assert r.adapter == {} and r.goal == "g"
