"""Thin wrapper around the TypeSafe SDK. The SDK reads TYPESAFE_API_KEY itself."""

from __future__ import annotations

import time
from dataclasses import dataclass

DEFAULT_MODEL = "jev-1.13.0"


@dataclass
class ChoiceResult:
    model: str
    choice: str
    confidence: float
    probabilities: dict[str, float]
    latency_ms: int
    input_tokens: int | None = None


class Jev:
    def __init__(self, model: str = DEFAULT_MODEL, client=None):
        self.model = model
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from typesafe_sdk import TypeSafeClient

            self._client = TypeSafeClient(model=self.model)
        return self._client

    def choice(self, state: dict, qid: str, instructions, criteria: dict) -> ChoiceResult:
        from typesafe_sdk import Choice

        start = time.perf_counter()
        resp = self.client.system_one(
            state=state,
            questions={qid: Choice(instructions=instructions, criteria=criteria)},
            model=self.model,
        )
        ans = resp.answers[qid]
        return ChoiceResult(
            model=resp.model,
            choice=ans.choice,
            confidence=ans.confidence,
            probabilities=dict(ans.probabilities),
            latency_ms=round((time.perf_counter() - start) * 1000),
            input_tokens=getattr(resp.usage, "input_tokens", None),
        )
