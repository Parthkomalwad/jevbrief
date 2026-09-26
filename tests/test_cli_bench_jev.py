"""The CLI, the benchmark runner, and the Jev wrapper, with no network: a fake SDK client and FakeJev."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jevbrief import cli
from jevbrief.bench import run
from jevbrief.jev import Jev
from jevbrief.testing import FakeJev

ROOT = Path(__file__).resolve().parent.parent
OTEL = ROOT / "bench" / "otel" / "checkout_500.json"


# Jev: the wrapper around the TypeSafe SDK

class FakeSdkClient:
    def __init__(self):
        self.calls = []

    def system_one(self, state, questions, model):
        self.calls.append((state, questions, model))
        answers = {qid: SimpleNamespace(model_dump=lambda qid=qid: {"type": "choice", "choice": "a", "confidence": 0.8})
                   for qid in questions}
        return SimpleNamespace(model="jev-test", answers=answers, usage=SimpleNamespace(input_tokens=42))


def test_jev_sends_every_question_in_one_call_and_reads_the_answers():
    client = FakeSdkClient()
    res = Jev("jev-test", client=client).ask({"items": []}, {
        "pick": {"type": "choice", "instructions": "Pick one", "criteria": {"a": "A", "none": "None"}},
        "sure": {"type": "noul", "instructions": "Is it done?"}})
    assert len(client.calls) == 1 and set(client.calls[0][1]) == {"pick", "sure"}
    assert type(client.calls[0][1]["pick"]).__name__ == "Choice" and type(client.calls[0][1]["sure"]).__name__ == "Noul"
    assert res.model == "jev-test" and res.input_tokens == 42 and res.answers["pick"]["choice"] == "a"
    assert res.latency_ms >= 0


# The benchmark runner

def tasks(tmp_path, **extra):
    shutil_src = tmp_path / "logs.json"
    shutil_src.write_bytes(OTEL.read_bytes())
    t = [{"adapter": "otel", "source": "logs.json", "goal": "Checkout fails", "expected_contains": "pool exhausted", **extra},
         {"adapter": "otel", "source": "logs.json", "goal": "not labeled yet"}]
    (tmp_path / "tasks.json").write_text(json.dumps(t), encoding="utf-8")
    return tmp_path / "tasks.json"


def test_bench_runs_both_arms_and_skips_unlabeled_tasks(tmp_path):
    table = run(str(tasks(tmp_path)), repeats=2, out_dir=str(tmp_path / "traces"), jev=FakeJev())
    lines = table.splitlines()
    assert lines[0].startswith("| Arm | Accuracy |") and lines[2].startswith("| raw | ") and lines[3].startswith("| jevbrief | ")
    assert "(2/2)" in lines[3] or "(0/2)" in lines[3]  # FakeJev picks the first option; the count is what matters
    assert sum(line.startswith("| logs") for line in lines) == 1  # the unlabeled task was skipped
    assert (tmp_path / "traces" / "raw.jsonl").exists() and (tmp_path / "traces" / "jevbrief.jsonl").exists()


# The command line

def test_cli_inspect_needs_no_key(capsys, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert cli.main(["inspect", str(OTEL), "--adapter", "otel", "--goal", "checkout fails"]) == 0
    out = capsys.readouterr().out
    assert "facts found" in out and "KEPT" in out and "otel.below_severity" in out


def test_cli_ask_and_bench_refuse_without_a_key(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert cli.main(["ask", str(OTEL), "--adapter", "otel", "--goal", "x"]) == 2
    assert cli.main(["bench", str(tmp_path / "tasks.json")]) == 2
    assert "TYPESAFE_API_KEY is not set" in capsys.readouterr().err


def test_cli_ask_writes_a_trace_and_view_renders_it(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-not-a-key")
    monkeypatch.setattr(Jev, "ask", lambda self, state, questions: FakeJev().ask(state, questions))
    trace = tmp_path / "t.jsonl"
    assert cli.main(["ask", str(OTEL), "--adapter", "otel", "--goal", "checkout fails", "--trace", str(trace)]) == 0
    out = capsys.readouterr().out
    assert "outcome: applied" in out and trace.exists()
    assert cli.main(["view", str(trace), "--no-open"]) == 0
    assert "viewer:" in capsys.readouterr().out


def test_cli_adapters_and_errors(capsys):
    assert cli.main(["adapters"]) == 0
    assert {"ci", "otel", "pr", "steps", "tools"} <= {ln.split()[0] for ln in capsys.readouterr().out.splitlines()}
    assert cli.main(["inspect", "missing.json", "--adapter", "otel", "--goal", "x"]) == 2
    assert "error:" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["--version"])


def test_load_env_keeps_existing_values(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("# comment\nexport JB_A='from file'\nJB_B=from file\n", encoding="utf-8")
    monkeypatch.setenv("JB_B", "already set")
    monkeypatch.delenv("JB_A", raising=False)
    cli.load_env(tmp_path / ".env")
    import os
    assert os.environ["JB_A"] == "from file" and os.environ["JB_B"] == "already set"
