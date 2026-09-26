"""adecide(), apick_tool(), acheck_progress(), and the Jev client's timeout, retries, and async path."""

import asyncio
import time
from types import SimpleNamespace

from test_otel import DATA

from jevbrief import Briefing
from jevbrief.adapters.otel import OtelAdapter
from jevbrief.jev import Answers, Jev
from jevbrief.testing import FakeJev


def fresh(jev):
    b = Briefing(OtelAdapter(), "checkout fails", trace=None, jev=jev)
    b.extract(DATA)
    return b


class AsyncFake(FakeJev):
    """A client with its own `aask`, like `Jev`: used instead of a worker thread."""

    def __init__(self):
        self.async_calls = 0

    async def aask(self, state, questions):
        self.async_calls += 1
        await asyncio.sleep(0)
        return self.ask(state, questions)


def test_adecide_matches_decide_and_uses_aask_when_there_is_one():
    sync = fresh(FakeJev()).decide()
    jev = AsyncFake()
    b = fresh(jev)
    d = asyncio.run(b.adecide())
    assert (d.outcome, d.choice, d.fact.id) == (sync.outcome, sync.choice, sync.fact.id) and jev.async_calls == 1
    again = asyncio.run(b.adecide())  # unchanged state: reused, no second call
    assert again.outcome == "reused" and jev.async_calls == 1


def test_adecide_runs_a_sync_client_in_a_thread_without_blocking_the_loop():
    class Slow(FakeJev):
        def ask(self, state, questions):
            time.sleep(0.3)
            return super().ask(state, questions)

    async def main():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        t = asyncio.create_task(ticker())
        d = await fresh(Slow()).adecide()
        t.cancel()
        return d, ticks

    d, ticks = asyncio.run(main())
    assert d.outcome == "applied" and ticks >= 5  # the loop kept running while Jev "thought"


def test_adecide_records_api_errors():
    class Down(FakeJev):
        async def aask(self, state, questions):
            raise ConnectionError("network down")

    d = asyncio.run(fresh(Down()).adecide())
    assert d.outcome == "error" and d.record.jev["error"] == "ConnectionError: network down"


def test_jev_passes_timeout_and_retries_to_both_sdk_clients(monkeypatch):
    import typesafe_sdk

    seen = []
    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", lambda **kw: seen.append(("sync", kw)) or object())
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", lambda **kw: seen.append(("async", kw)) or object())
    j = Jev("jev-x", timeout=7.5, retries=4)
    assert j.client and j.async_client
    assert [k for k, _ in seen] == ["sync", "async"]
    for _, kw in seen:
        assert kw["model"] == "jev-x" and kw["timeout"] == 7.5 and kw["retry"].max_retries == 4
    seen.clear()
    assert Jev("jev-x").client
    assert seen == [("sync", {"model": "jev-x"})]  # SDK defaults when not set


def test_jev_aask_uses_the_async_client():
    class Client:
        async def system_one(self, state, questions, model):
            answers = {q: SimpleNamespace(model_dump=lambda: {"type": "choice", "choice": "a", "confidence": 0.7})
                       for q in questions}
            return SimpleNamespace(model=model, answers=answers, usage=SimpleNamespace(input_tokens=9))

        async def aclose(self):
            self.closed = True

    client = Client()
    j = Jev("jev-x", async_client=client)
    res = asyncio.run(j.aask({}, {"pick": {"type": "choice", "instructions": "x", "criteria": {"a": "A"}}}))
    assert isinstance(res, Answers) and res.answers["pick"]["choice"] == "a" and res.input_tokens == 9
    asyncio.run(j.aclose())
    assert client.closed and j._async_client is None


def test_apick_tool_and_acheck_progress_match_the_sync_versions():
    from jevbrief import acheck_progress, apick_tool, check_progress, pick_tool

    def refund_order(order_id: str):
        """Refund a customer's order."""

    def lookup_customer(email: str):
        """Find a customer by email."""

    tools = [refund_order, lookup_customer]
    sync = pick_tool(tools, "refund order 812", trace=None, jev=FakeJev())
    got = asyncio.run(apick_tool(tools, "refund order 812", trace=None, jev=AsyncFake()))
    assert got.tool is sync.tool and got.tools == sync.tools

    steps = [{"tool": "search_code", "args": {"q": "x"}, "result": "0 results"}] * 5
    sync_p = check_progress(steps, "find x", trace=None, jev=FakeJev())
    got_p = asyncio.run(acheck_progress(steps, "find x", trace=None, jev=AsyncFake()))
    assert (got_p.verdict, got_p.advice, got_p.signals) == (sync_p.verdict, sync_p.advice, sync_p.signals)
