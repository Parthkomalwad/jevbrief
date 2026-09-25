import json
from pathlib import Path
from types import SimpleNamespace

import jevbrief
from jevbrief import Briefing
from jevbrief.adapters.steps import StepsAdapter, check_progress, loop_signals, normalize, signals
from jevbrief.testing import FakeJev, check_adapter


def step(tool, args=None, result=None, error=None):
    return {"tool": tool, "args": args or {}, "result": result, "error": error}


STUCK = [step("list_issues", {"repo": "acme/shop"}, "12 issues"),
         *[step("search_code", {"q": "parse_invoice"}, "0 results") for _ in range(5)]]
FAILING = [step("create_pull_request", {"head": "fix"}, error="422 Validation Failed: no commits between main and fix")
           for _ in range(4)]
CYCLE = [step(t, {}, r) for t, r in [("git_status", "clean"), ("git_diff", "no changes")] * 3]
PAGING = [step("list_issues", {"page": p}, f"issues {p * 30}-{p * 30 + 29}") for p in range(1, 6)]
POLLING = [step("get_job", {"id": 7}, s) for s in ("queued", "running", "running 40%", "running 80%", "done")]


def brief(history, goal="fix the invoice bug", **config):
    b = Briefing(StepsAdapter(config), goal, trace=None, jev=FakeJev())
    b.extract(history)
    return b


def kinds(history):
    return {s["kind"]: s for s in signals(normalize(history))}


def test_contract(tmp_path):
    path = tmp_path / "steps.json"
    path.write_text(json.dumps(STUCK), encoding="utf-8")
    check_adapter(StepsAdapter(), path, goal="find where parse_invoice is defined")


def test_signals_count_loops():
    s = kinds(STUCK)
    assert s["repeat"]["attrs"] == {"in_a_row": 5, "same_result_each_time": "yes"}
    assert s["novelty"]["attrs"]["steps_since_new_information"] == 4
    e = kinds(FAILING)["errors"]
    assert e["strength"] == 4 and e["attrs"]["failing_in_a_row"] == 4 and "422 Validation Failed" in e["label"]
    assert kinds(CYCLE)["cycle"]["label"] == "a cycle repeated 3 times: git_status -> git_diff"


def test_progress_is_not_a_loop():
    assert kinds(POLLING)["repeat"]["label"].endswith("a different result each time")  # counted, not hidden
    for history in (PAGING, POLLING):  # the same tool again, but new arguments or new results each time
        assert "cycle" not in kinds(history) and kinds(history).get("repeat", {}).get("strength", 0) in (0, 5)
        assert kinds(history)["novelty"]["attrs"]["steps_since_new_information"] == 0
        assert loop_signals(history) == []


def test_loop_signals_in_words():
    assert loop_signals(STUCK) == ["search_code called 5 times in a row with the same arguments, the same result each time",
                                   "new information in 2 of the last 6 steps"]


def test_every_reason_code():
    history = [step(f"tool_{i}", {"i": i}, f"r{i}") for i in range(10)] + [step("retry", {}, "same")] * 2
    r = {f.label + ("" if f.kind == "step" else f":{f.kind}"): f.reason for f in brief(history, recent=4).facts}
    assert r["tool_0"] == "steps.old" and r["tool_9"] == "steps.recent"
    assert r[next(k for k in r if k.endswith(":repeat"))] == "steps.weak_signal"  # twice in a row is a normal retry
    r = {f.kind: f.reason for f in brief(STUCK).facts if f.kind != "step"}
    assert r["repeat"] == "steps.loop" and r["novelty"] == "base"


def test_state_sent_to_jev():
    s = brief(STUCK).state()
    assert [x["kind"] for x in s["signals"]] == ["repeat", "novelty"]
    assert [x["step"] for x in s["steps"]][-2:] == ["2 steps ago", "the latest step"]  # oldest first
    assert s["steps"][-1] == {"id": s["steps"][-1]["id"], "kind": "step", "label": "search_code",
                              "step": "the latest step", "args": '{"q": "parse_invoice"}', "result": "0 results"}


# --- Any history ---

def test_openai_messages():
    msgs = [{"role": "user", "content": "fix it"}]
    for i in range(3):
        msgs += [{"role": "assistant", "tool_calls": [{"id": f"c{i}", "type": "function",
                  "function": {"name": "run_tests", "arguments": '{"path": "tests"}'}}]},
                 {"role": "tool", "tool_call_id": f"c{i}", "content": "1 failed"}]
    steps = normalize(msgs)
    assert [(s["action"], s["result"]) for s in steps] == [("run_tests", "1 failed")] * 3


def test_anthropic_messages():
    msgs = []
    for i in range(3):
        msgs += [{"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "fetch", "input": {"url": "x"}}]},
                 {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "is_error": True,
                                               "content": "timeout"}]}]
    assert [(s["action"], s["error"]) for s in normalize(msgs)] == [("fetch", "timeout")] * 3


def test_langchain_messages():
    msgs = []
    for i in range(3):
        msgs += [SimpleNamespace(type="ai", content="", tool_calls=[{"name": "search", "args": {"q": "a"}, "id": f"l{i}"}]),
                 SimpleNamespace(type="tool", role=None, content="nothing", tool_call_id=f"l{i}", status="success")]
    for m in msgs:  # LangChain ToolMessage has type "tool"
        m.role = m.type
    assert [(s["action"], s["result"]) for s in normalize(msgs)] == [("search", "nothing")] * 3


def test_jevbrief_trace(tmp_path):
    lines = []
    for i in range(8):
        lines.append({"run_id": "r1", "facts": [{"id": "e1", "label": "Nova"}], "outcome": "reused" if i else "applied",
                      "jev": {"choice": "jump_right"}, "fingerprint": {"hash": "same"}})
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    assert loop_signals(path)[0] == "jump_right called 8 times in a row with the same arguments, the same result each time"


def test_real_nes_trace_is_stuck():
    path = Path(__file__).resolve().parent.parent / "traces" / "nes.jsonl"
    if path.exists():  # traces are not committed; this runs where the demo has been played
        assert "jump_right called 20 times in a row" in loop_signals(path)[0]


def test_check_progress(tmp_path):
    p = check_progress(STUCK, "find parse_invoice", jev=FakeJev(), trace=str(tmp_path / "p.jsonl"))
    assert p.verdict == "progressing" and p.stuck is False  # FakeJev picks the first option
    assert p.advice == "continue" and p.probability == 0.5
    assert p.signals[0].startswith("search_code called 5 times")
    assert jevbrief.check_progress is check_progress and jevbrief.loop_signals is loop_signals
