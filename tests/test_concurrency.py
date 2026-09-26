"""Threads, processes, and event loops: shared adapters, one trace file, run IDs, and the Jev async client."""

import asyncio
import copy
import json
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest

from jevbrief import Briefing, get_adapter
from jevbrief.testing import FakeJev

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
OTEL = BENCH / "otel" / "checkout_500.json"


def facts_of(adapter, source, **kw):
    b = Briefing(adapter, "find the cause", trace=None, jev=FakeJev())
    b.extract(source, **kw)
    return [(f.id, f.reason, f.score) for f in b.facts]


def sources():
    """One committed input per built-in adapter that reads files (web and nes have their own tests)."""
    from test_ci import write as ci_input
    from test_pr import DIFF

    yield "otel", str(OTEL), {}
    yield "otel", str(BENCH / "incident" / "oom_checkout"), {}
    yield "json", str(BENCH / "json" / "tickets.json"), {"config": str(BENCH / "json" / "tickets.toml")}
    yield "tools", str(BENCH / "mcp" / "tools"), {}
    yield "steps", str(next((BENCH / "steps" / "histories").iterdir())), {}
    yield "pr", DIFF, {}
    yield "ci", ci_input, {}


def test_every_adapter_can_be_shared_by_many_threads(tmp_path):
    for name, source, kw in sources():
        source = source(tmp_path) if callable(source) else source
        adapter = get_adapter(name)
        if "config" in kw:
            adapter.configure(kw.pop("config"))
        expected = facts_of(adapter, source, **kw)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _, a=adapter, s=source, k=kw: facts_of(a, s, **k), range(32)))
        assert all(r == expected for r in results), name


def test_threads_sharing_one_trace_file_lose_nothing(tmp_path):
    trace = tmp_path / "shared.jsonl"
    ex = get_adapter("otel").extract(str(OTEL))

    def work():
        for _ in range(15):
            b = Briefing(get_adapter("otel"), "checkout", trace=str(trace), jev=FakeJev())
            b.load_extracted(copy.deepcopy(ex))
            b.decide()

    threads = [threading.Thread(target=work) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    records = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 16 * 15
    assert len({(r["run_id"], r["tick"]) for r in records}) == len(records)


def process_work(trace: str) -> int:
    for _ in range(25):
        b = Briefing(get_adapter("otel"), "checkout", trace=trace, jev=FakeJev())
        b.extract(str(OTEL))
        b.decide()
    return 25


def test_processes_sharing_one_trace_file_lose_nothing(tmp_path):
    trace = str(tmp_path / "shared.jsonl")
    with ProcessPoolExecutor(max_workers=4) as pool:  # spawn on Windows and macOS: workers build their own Briefing
        done = sum(pool.map(process_work, [trace] * 4))
    records = [json.loads(line) for line in Path(trace).read_text(encoding="utf-8").splitlines()]
    assert done == len(records) == 100
    assert len({r["run_id"] for r in records}) == 100


def test_run_ids_do_not_collide():
    ids = {Briefing(get_adapter("otel"), "g", trace=None, jev=FakeJev()).run_id for _ in range(5000)}
    assert len(ids) == 5000


def test_two_json_configs_keep_their_own_reason_descriptions(tmp_path):
    base = {"items": "rows", "id": "{id}", "label": "{name}", "send": ["age"]}
    data = {"rows": [{"id": 1, "name": "old", "age": 400}, {"id": 2, "name": "new", "age": 1}]}

    def trace_legend(description, limit):
        cfg = {**base, "rules": [{"name": "stale", "description": description, "drop_if": {"field": "age", "greater_than": limit}}]}
        path = tmp_path / f"{limit}.jsonl"
        b = Briefing(get_adapter("json"), "anything", trace=str(path), jev=FakeJev())
        b.extract(data, config=cfg)
        return b, path

    a, a_path = trace_legend("Older than 30 days", 30)
    b, b_path = trace_legend("Not touched this year", 365)
    a.decide()  # decided after b's config was loaded
    b.decide()
    assert json.loads(a_path.read_text(encoding="utf-8"))["reasons"]["json.stale"] == "Older than 30 days"
    assert json.loads(b_path.read_text(encoding="utf-8"))["reasons"]["json.stale"] == "Not touched this year"


def test_jev_uses_one_async_client_per_event_loop(monkeypatch):
    import typesafe_sdk

    from jevbrief.jev import Jev

    made = []
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", lambda **kw: made.append(object()) or made[-1])
    j = Jev()

    async def twice():
        return j.async_client, j.async_client

    first = asyncio.run(twice())
    second = asyncio.run(twice())
    assert first[0] is first[1] and second[0] is second[1]  # the same client within a loop
    assert first[0] is not second[0] and len(made) == 2     # a new one for a new loop

    mine = object()
    assert Jev(async_client=mine).async_client is mine      # a client you pass is always used


@pytest.mark.parametrize("n", [8])
def test_fastembed_model_loads_once_across_threads(monkeypatch, n):
    pytest.importorskip("fastembed")
    import fastembed

    from jevbrief.adapters.tools import Embedder

    loads = []

    class Slow:
        def __init__(self, model):
            loads.append(model)
            threading.Event().wait(0.05)

    monkeypatch.setattr(fastembed, "TextEmbedding", Slow)
    e = Embedder(model="m")
    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(lambda _: e._fastembed(), range(n)))
    assert loads == ["m"]
