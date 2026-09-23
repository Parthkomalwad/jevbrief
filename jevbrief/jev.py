"""Thin wrapper around the TypeSafe SDK. The SDK reads TYPESAFE_API_KEY itself."""

from __future__ import annotations

import time
from dataclasses import dataclass

DEFAULT_MODEL = "jev-1.13.0"


@dataclass
class Answers:
    model: str
    answers: dict[str, dict]  # question id -> {"type", "choice"/"noul"/"score", "confidence", "probabilities", ...}
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

    def ask(self, state, questions: dict[str, dict]) -> Answers:
        """Ask every question against the same state in one call. Questions are plain API-shaped dicts."""
        import typesafe_sdk as ts

        types = {"choice": ts.Choice, "noul": ts.Noul, "score": ts.Score}
        sdk_questions = {qid: types[q["type"]](**{k: v for k, v in q.items() if k != "type"})
                         for qid, q in questions.items()}
        start = time.perf_counter()
        resp = self.client.system_one(state=state, questions=sdk_questions, model=self.model)
        latency = round((time.perf_counter() - start) * 1000)
        answers = {qid: a.model_dump() if hasattr(a, "model_dump") else dict(a) for qid, a in resp.answers.items()}
        return Answers(resp.model, answers, latency, getattr(resp.usage, "input_tokens", None))
