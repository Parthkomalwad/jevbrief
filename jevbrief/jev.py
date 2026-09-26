"""Thin wrapper around the TypeSafe SDK. The SDK reads TYPESAFE_API_KEY itself."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

DEFAULT_MODEL = "jev-1.13.0"


@dataclass
class Answers:
    model: str
    answers: dict[str, dict]  # question id -> {"type", "choice"/"noul"/"score", "confidence", "probabilities", ...}
    latency_ms: int
    input_tokens: int | None = None


class JevClient(Protocol):
    """What a Briefing needs from Jev: a model name and `ask`. `Jev` and `testing.FakeJev` both fit."""

    model: str

    def ask(self, state, questions: dict[str, dict]) -> Answers: ...


class Jev:
    """The TypeSafe SDK client, for one model.

    `timeout` is seconds per request, and `retries` is how many times a failed request is retried
    (connection errors, timeouts, rate limits, and server errors, with backoff). Both default to the SDK's.
    Pass `client` or `async_client` to use your own SDK clients, for example with a shared HTTP client.
    """

    def __init__(self, model: str = DEFAULT_MODEL, client=None, *, async_client=None,
                 timeout: float | None = None, retries: int | None = None):
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self._client = client
        self._async_client = async_client

    def _options(self) -> dict:
        opts: dict = {"model": self.model}
        if self.timeout is not None:
            opts["timeout"] = self.timeout
        if self.retries is not None:
            from typesafe_sdk import RetryPolicy

            opts["retry"] = RetryPolicy(max_retries=self.retries)
        return opts

    @property
    def client(self):
        if self._client is None:
            from typesafe_sdk import TypeSafeClient

            self._client = TypeSafeClient(**self._options())
        return self._client

    @property
    def async_client(self):
        if self._async_client is None:
            from typesafe_sdk import AsyncTypeSafeClient

            self._async_client = AsyncTypeSafeClient(**self._options())
        return self._async_client

    def ask(self, state, questions: dict[str, dict]) -> Answers:
        """Ask every question against the same state in one call. Questions are plain API-shaped dicts."""
        start = time.perf_counter()
        resp = self.client.system_one(state=state, questions=_sdk_questions(questions), model=self.model)
        return _answers(resp, start)

    async def aask(self, state, questions: dict[str, dict]) -> Answers:
        """`ask` without blocking the event loop, on the SDK's async client."""
        start = time.perf_counter()
        resp = await self.async_client.system_one(state=state, questions=_sdk_questions(questions), model=self.model)
        return _answers(resp, start)

    async def aclose(self) -> None:
        """Close the async client's connections. The sync client is closed by `close`."""
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def _sdk_questions(questions: dict[str, dict]) -> dict:
    import typesafe_sdk as ts

    types = {"choice": ts.Choice, "noul": ts.Noul, "score": ts.Score}
    return {qid: types[q["type"]](**{k: v for k, v in q.items() if k != "type"}) for qid, q in questions.items()}


def _answers(resp, start: float) -> Answers:
    latency = round((time.perf_counter() - start) * 1000)
    answers = {qid: a.model_dump() if hasattr(a, "model_dump") else dict(a) for qid, a in resp.answers.items()}
    return Answers(resp.model, answers, latency, getattr(resp.usage, "input_tokens", None))


def api_errors() -> tuple[type[BaseException], ...]:
    """Failures that are Jev's or the network's, not bugs: they become `outcome="error"` instead of raising.

    TypeSafeError covers the SDK's API, authentication (a missing key), rate limit, timeout, and connection
    errors. OSError covers connection and timeout errors raised by custom clients.
    """
    from typesafe_sdk import TypeSafeError

    return (TypeSafeError, OSError)
