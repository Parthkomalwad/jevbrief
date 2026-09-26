"""The generic pipeline: extract, rules, budget, fingerprint, ask Jev, trace. Works with any adapter."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field

from . import budget, trace
from .facts import BUDGET, REASONS, Fact
from .fingerprint import fingerprint
from .jev import DEFAULT_MODEL, Answers, Jev, JevClient, api_errors
from .questions import QuestionPack
from .rules import RuleSet


@dataclass
class Extracted:
    """What an adapter's extractor returns."""
    facts: list[Fact]
    source: dict = field(default_factory=dict)  # small context for rules, state, and the trace (url, viewport_h, ...)
    image: bytes | None = None                  # optional snapshot for the spatial viewer
    image_size: tuple[int, int] | None = None   # (width, height) of the coordinate space of `Fact.box`
    raw: list[Fact] | None = None               # the benchmark's raw arm, when it needs more than `facts`


@dataclass
class Decision:
    fact: Fact | None               # the chosen fact, when the pack's options are facts and the outcome is applied
    outcome: str                    # applied | reused | low_confidence | error
    choice: str | None = None       # the primary answer's option
    confidence: float | None = None
    answers: dict = field(default_factory=dict)  # every answer in the call
    record: trace.TraceRecord | None = None


class _Call:
    """One decision in progress: the questions to ask, then the answer or the failure."""

    def __init__(self, brief: Briefing, kept: list[Fact], fp: str, jev_info: dict):
        self.brief, self.kept, self.fp, self.jev_info = brief, kept, fp, jev_info
        self.fp_info: dict = {"hash": fp, "changed": True, "reused_tick": None}
        self.state: dict = {}
        self.questions: dict = {}
        self.decision: Decision | None = None

    def answered(self, res: Answers) -> None:
        b = self.brief
        main = res.answers.get(b.pack.primary, {})
        choice, conf = main.get("choice"), main.get("confidence")
        self.jev_info.update(model=res.model, choice=choice, confidence=conf, probabilities=main.get("probabilities"),
                             latency_ms=res.latency_ms, input_tokens=res.input_tokens)
        if choice is None or choice == "none" or conf is None or conf < b.min_confidence:
            self.decision = Decision(None, "low_confidence", choice, conf, res.answers)
        else:
            self.decision = Decision(b.pack.fact_for(choice, self.kept), "applied", choice, conf, res.answers)

    def failed(self, e: BaseException) -> None:
        self.jev_info["error"] = f"{type(e).__name__}: {e}"
        self.decision = Decision(None, "error")


class Briefing:
    def __init__(self, adapter, goal: str, *, pack: str | QuestionPack | None = None, rules: RuleSet | None = None,
                 budget_tokens: int = budget.DEFAULT_TOKENS, max_options: int = budget.DEFAULT_OPTIONS,
                 trace: str | None = "trace.jsonl", trace_level: str = "summary", min_confidence: float = 0.5,
                 pins=(), model: str = DEFAULT_MODEL, jev: JevClient | None = None, images: bool = True):
        if trace_level not in trace_levels():
            raise ValueError("trace_level must be off, summary, or full")
        self.adapter = adapter
        self.goal = goal
        packs = adapter.packs()
        self.pack = pack if isinstance(pack, QuestionPack) else packs[pack or next(iter(packs))]
        self._own_rules = rules is not None
        self.rules = rules or adapter.rules()
        self.budget_tokens = budget_tokens
        self.max_options = max_options
        self.trace_path = trace
        self.trace_level = trace_level
        self.min_confidence = min_confidence
        self.pins = list(pins)
        self.jev: JevClient = jev or Jev(model)
        self.images = images
        self.run_id = "r_" + secrets.token_hex(6)  # 48 bits: no collisions across many runs and processes
        self.tick = 0
        self.source: dict = {}
        self.image: bytes | None = None
        self.image_size: tuple[int, int] | None = None
        self.facts: list[Fact] = []
        self.used_tokens = 0
        self._last: tuple[str, int, Decision] | None = None  # (hash, tick, decision)

    @property
    def kept(self) -> list[Fact]:
        return [f for f in self.facts if f.kept]

    def state(self) -> dict:
        return self.adapter.state(self.goal, self.kept, self.source)

    def extract(self, source, **options) -> list[Fact]:
        """Run the adapter's extractor on `source`, then filter and budget the facts.

        The adapter's rules are rebuilt after extracting, so config loaded by `extract` and per-call
        options (such as `min_severity`) apply. Rules passed to `Briefing(rules=...)` are kept as given.
        """
        from .adapters import adapter_rules

        ex = self.adapter.extract(source, **options)
        if not self._own_rules:
            self.rules = adapter_rules(self.adapter, options)
        return self.load_extracted(ex)

    def load_extracted(self, ex: Extracted) -> list[Fact]:
        keep_image = self.images and self.trace_level != "off"
        self.image = ex.image if keep_image else None
        self.image_size = ex.image_size
        return self.load(ex.facts, ex.source)

    def load(self, facts: list[Fact], source: dict | None = None) -> list[Fact]:
        """Filter and budget facts you already have."""
        self.source = dict(source or {})
        self.facts = self.rules.apply(facts, self.goal, self.pins, self.source)
        base = {k: v for k, v in self.adapter.state(self.goal, [], self.source).items() if v != []}
        self.used_tokens = budget.fit(self.facts, self.budget_tokens, self.max_options, base=base)
        return self.facts

    def decide(self) -> Decision:
        """Ask Jev the pack's questions. Reuses the last decision if the kept state is unchanged.

        Jev and network failures give `outcome="error"`. Any other exception is a bug and is raised.
        """
        call = self._begin()
        if call.questions:
            try:
                call.answered(self.jev.ask(call.state, call.questions))
            except api_errors() as e:
                call.failed(e)
        return self._finish(call)

    async def adecide(self) -> Decision:
        """`decide()` for async code: the same result, without blocking the event loop.

        Uses the Jev client's `aask` when it has one, and otherwise runs `ask` in a worker thread.
        """
        call = self._begin()
        if call.questions:
            try:
                aask = getattr(self.jev, "aask", None)
                res = await (aask(call.state, call.questions) if aask
                             else asyncio.to_thread(self.jev.ask, call.state, call.questions))
                call.answered(res)
            except api_errors() as e:
                call.failed(e)
        return self._finish(call)

    def _begin(self) -> _Call:
        self.tick += 1
        kept = self.kept
        fp = fingerprint(kept, self.goal)
        call = _Call(self, kept, fp, {"model": self.jev.model, "question": self.pack.primary})
        if self._last and self._last[0] == fp:
            prev = self._last[2]
            call.decision = Decision(prev.fact, "reused", prev.choice, prev.confidence, prev.answers)
            call.fp_info = {"hash": fp, "changed": False, "reused_tick": self._last[1]}
            call.jev_info.update(choice=prev.choice, confidence=prev.confidence)
        else:
            call.state = self.state()
            call.questions = self.pack.build(self.goal, kept, call.state)
        return call

    def _finish(self, call: _Call) -> Decision:
        decision = call.decision
        assert decision is not None
        if call.fp_info["changed"] and decision.outcome != "error":
            self._last = (call.fp, self.tick, decision)
        record = self._record(call.fp_info, call.jev_info, decision, call.questions)
        decision.record = record
        if record and self.trace_path:
            trace.write(self.trace_path, record, image=self.image)
        return decision

    def _record(self, fp_info: dict, jev_info: dict, decision: Decision, questions: dict) -> trace.TraceRecord | None:
        if self.trace_level == "off":
            return None
        level = self.trace_level
        facts = [f.to_dict(level) for f in self.facts]
        if level == "summary":  # labels, scores, and boxes help the viewer; still small
            for d, f in zip(facts, self.facts, strict=True):
                d.update(kind=f.kind, label=f.label, score=f.score, box=f.box)
                if "view" in f.meta:  # adapter-provided layout hints for the viewer, such as a timeline span
                    d["view"] = f.meta["view"]
        own = getattr(self.adapter, "reason_descriptions", None)
        legend = {**REASONS, **(own() if own else {}),
                  **{r.name: r.description for r in self.rules.rules if r.description}}
        image = None
        if self.image is not None:
            w, h = self.image_size or (0, 0)
            image = {"path": "", "width": w, "height": h}
        return trace.TraceRecord(
            run_id=self.run_id,
            tick=self.tick,
            adapter={"name": self.adapter.name, "version": self.adapter.version, "renderer": self.adapter.renderer},
            source={**self.source, "raw_facts": len(self.facts)},
            goal=self.goal,
            facts=facts,
            budget={"limit_tokens": self.budget_tokens, "used_tokens": self.used_tokens,
                    "cut_for_budget": sum(f.reason == BUDGET for f in self.facts)},
            fingerprint=fp_info,
            jev=jev_info,
            outcome=decision.outcome,
            answers=decision.answers,
            questions=questions if level == "full" else {},
            reasons={f.reason: legend.get(f.reason, "") for f in self.facts},
            image=image,
            state=self.state() if level == "full" else None,
        )


def trace_levels() -> tuple[str, ...]:
    return trace.LEVELS
