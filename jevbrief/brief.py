"""The Brief pipeline: extract, filter, budget, fingerprint, ask Jev, trace."""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass

from . import budget, dom, questions, salience, trace
from .facts import BUDGET, Fact
from .fingerprint import fingerprint
from .jev import DEFAULT_MODEL, Jev


@dataclass
class Decision:
    fact: Fact | None
    outcome: str
    choice: str | None = None
    confidence: float | None = None
    record: trace.TraceRecord | None = None


class Brief:
    def __init__(self, goal: str, budget_tokens: int = budget.DEFAULT_TOKENS,
                 max_options: int = budget.DEFAULT_OPTIONS, trace: str | None = "trace.jsonl",
                 trace_level: str = "summary", min_confidence: float = 0.5, pins=(),
                 model: str = DEFAULT_MODEL, jev: Jev | None = None, screenshot: bool = True):
        if trace_level not in ("off", "summary", "full"):
            raise ValueError("trace_level must be off, summary, or full")
        self.goal = goal
        self.budget_tokens = budget_tokens
        self.max_options = max_options
        self.trace_path = trace
        self.trace_level = trace_level
        self.min_confidence = min_confidence
        self.pins = list(pins)
        self.jev = jev or Jev(model)
        self.screenshot = screenshot
        self.page_image: dict | None = None
        self.run_id = "r_" + secrets.token_hex(2)
        self.tick = 0
        self.url = ""
        self.facts: list[Fact] = []
        self.used_tokens = 0
        self._last: tuple[str, int, Decision] | None = None  # (hash, tick, decision)

    @property
    def kept(self) -> list[Fact]:
        return [f for f in self.facts if f.kept]

    def state(self) -> dict:
        return questions.state(self.goal, self.url, self.kept)

    def load(self, facts: list[Fact], url: str = "", viewport_h: int = 800) -> list[Fact]:
        """Run salience and budget on already extracted facts."""
        self.url = url
        self.facts = salience.score(facts, self.goal, self.pins, viewport_h)
        self.used_tokens = budget.fit(self.facts, self.budget_tokens, self.max_options,
                                      base={"goal": self.goal, "url": url})
        return self.facts

    async def from_page(self, page) -> list[Fact]:
        """Extract facts from a Playwright page, then filter and budget them."""
        facts = await dom.extract(page)
        size = page.viewport_size or {"width": 1280, "height": 800}
        if self.screenshot and self.trace_level != "off":
            jpg = await page.screenshot(type="jpeg", quality=55)
            self.page_image = {"image": "data:image/jpeg;base64," + base64.b64encode(jpg).decode(),
                               "width": size["width"], "height": size["height"]}
        return self.load(facts, page.url, size["height"])

    def next_click(self) -> Decision:
        """Ask Jev which element to click next. Reuses the last answer if the state is unchanged."""
        self.tick += 1
        kept = self.kept
        fp = fingerprint(kept, self.goal)
        jev_info: dict = {"model": self.jev.model, "question": questions.QUESTION}

        if self._last and self._last[0] == fp:
            prev = self._last[2]
            decision = Decision(prev.fact, "reused", prev.choice, prev.confidence)
            fp_info = {"hash": fp, "changed": False, "reused_tick": self._last[1]}
            jev_info.update(choice=prev.choice, confidence=prev.confidence)
        else:
            fp_info = {"hash": fp, "changed": True, "reused_tick": None}
            q = questions.next_click(self.goal, kept)
            try:
                res = self.jev.choice(self.state(), questions.QUESTION, q["instructions"], q["criteria"])
            except Exception as e:  # any API or network failure: record it, take no action
                jev_info["error"] = f"{type(e).__name__}: {e}"
                decision = Decision(None, "error")
            else:
                jev_info.update(model=res.model, choice=res.choice, confidence=res.confidence,
                                probabilities=res.probabilities, latency_ms=res.latency_ms,
                                input_tokens=res.input_tokens)
                fact = questions.answer_fact(res.choice, kept)
                if fact is None or res.confidence < self.min_confidence:
                    decision = Decision(None, "low_confidence", res.choice, res.confidence)
                else:
                    decision = Decision(fact, "applied", res.choice, res.confidence)
            if decision.outcome != "error":
                self._last = (fp, self.tick, decision)

        record = self._record(fp_info, jev_info, decision.outcome)
        decision.record = record
        if record and self.trace_path:
            trace.write(self.trace_path, record)
        return decision

    def _record(self, fp_info: dict, jev_info: dict, outcome: str) -> trace.TraceRecord | None:
        if self.trace_level == "off":
            return None
        level = self.trace_level
        facts = [f.to_dict(level) for f in self.facts]
        if level == "summary":  # labels of kept facts help the viewer; still small
            for d, f in zip(facts, self.facts):
                d.update(kind=f.kind, label=f.label, score=f.score, box=f.box)
        return trace.TraceRecord(
            run_id=self.run_id,
            tick=self.tick,
            source={"adapter": "dom", "url": self.url, "raw_facts": len(self.facts)},
            goal=self.goal,
            facts=facts,
            budget={"limit_tokens": self.budget_tokens, "used_tokens": self.used_tokens,
                    "cut_for_budget": sum(f.reason == BUDGET for f in self.facts)},
            fingerprint=fp_info,
            jev=jev_info,
            outcome=outcome,
            state=self.state() if level == "full" else None,
            page=self.page_image,
        )
