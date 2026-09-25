"""The steps adapter: an agent's recent steps to progress facts, for noticing when it is stuck.

Takes the history in whatever shape you have:
- a list of step dicts: `{"tool": ..., "args": ..., "result": ..., "error": ...}` (also `action`, `name`,
  `input`, `output`, `observation`, `state`)
- OpenAI or Anthropic chat messages, or LangChain / LangGraph message objects, with tool calls and tool results
- a jevbrief trace file (`.jsonl`): each decision is a step, and its fingerprint is the state

Loops are counted in code, because Jev is weak at counting: the same call again, the same result again,
the same error again, an A-B-A-B cycle, and steps that brought no new information. Jev gets those signals
as words, plus the last few steps, and answers whether the agent is making progress. Standard library only.

    from jevbrief import check_progress, loop_signals
    loop_signals(steps)                    # local and free: ["search_code called 5 times in a row ...", ...]
    p = check_progress(steps, goal)        # asks Jev: p.stuck, p.verdict, p.advice, p.probability
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ...briefing import Briefing, Decision, Extracted
from ...facts import Fact, clean_label, fact_id, register_reasons
from ...questions import OptionChoice
from ...rules import CORE_RULES, Boost, Drop, Rule, RuleSet
from .. import Adapter

OLD = "steps.old"
WEAK = "steps.weak_signal"
REASONS = {
    OLD: "An older step, before the recent window",
    WEAK: "A pattern too small to matter (for example, a call made only twice)",
    "steps.loop": "Kept: the agent is repeating calls, results, or errors",
    "steps.recent": "Kept: one of the most recent steps",
}
WINDOW = 20        # steps looked at for patterns
RECENT = 6         # most recent steps sent to Jev one by one
MIN_REPEAT = 3     # a call, result, or error seen this many times is a pattern
TEXT_MAX = 120

VERDICTS = {
    "progressing": "Making progress: recent steps bring new information or move toward the goal",
    "stuck_repeating": "Stuck: repeating the same calls, or cycling between calls, without new information",
    "stuck_failing": "Stuck: the same error keeps happening and the agent keeps retrying",
    "done": "The goal looks complete: the agent should stop and answer",
}
ADVICE = {
    "continue": "Keep going as planned",
    "change_arguments": "Call the same tool with different arguments",
    "try_different_tool": "Use a different tool or approach",
    "ask_user": "Stop and ask the user for help or missing information",
    "stop": "Stop: the goal is done or cannot be reached",
}


# --- Reading any history -----------------------------------------------------------------------------

def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):  # content blocks
        return " ".join(_text(b.get("text", b) if isinstance(b, dict) else b) for b in v)
    try:
        return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        return str(v)


def _get(obj, *keys, default=None):
    for k in keys:
        v = obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)
        if v is not None:
            return v
    return default


def _from_messages(msgs) -> list[dict]:
    """Steps from OpenAI, Anthropic, or LangChain messages: each tool call, matched to its result by ID."""
    steps, by_id = [], {}
    for m in msgs:
        role = _get(m, "role", "type", default="")
        calls = _get(m, "tool_calls", default=None) or []
        for c in calls:  # OpenAI {"function": {"name", "arguments"}} or LangChain {"name", "args", "id"}
            fn = _get(c, "function", default=None) or c
            step = {"action": _get(fn, "name", default="?"), "args": _get(fn, "arguments", "args", default={}),
                    "result": None, "error": None}
            by_id[_get(c, "id", default=len(by_id))] = step
            steps.append(step)
        content = _get(m, "content", default=None)
        if isinstance(content, list):  # Anthropic content blocks
            for b in content:
                t = _get(b, "type")
                if t == "tool_use":
                    step = {"action": _get(b, "name", default="?"), "args": _get(b, "input", default={}),
                            "result": None, "error": None}
                    by_id[_get(b, "id")] = step
                    steps.append(step)
                elif t == "tool_result" and _get(b, "tool_use_id") in by_id:
                    s = by_id[_get(b, "tool_use_id")]
                    s["error" if _get(b, "is_error") else "result"] = _text(_get(b, "content"))
        call_id = _get(m, "tool_call_id", default=None)
        if call_id is not None and call_id in by_id and role in ("tool", "ToolMessage"):
            s = by_id[call_id]
            s["error" if _get(m, "status") == "error" else "result"] = _text(content)
    return steps


def _from_trace(path: Path) -> list[dict]:
    """Steps from a jevbrief trace: the chosen fact (or option) is the action, the fingerprint is the state."""
    steps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        choice = (r.get("jev") or {}).get("choice")
        label = next((f.get("label") for f in r.get("facts", []) if f.get("id") == choice), None) or choice or "none"
        steps.append({"action": label, "args": "", "result": None,
                      "error": (r.get("jev") or {}).get("error"), "state": (r.get("fingerprint") or {}).get("hash"),
                      "run": r.get("run_id")})
    if steps and len({s["run"] for s in steps}) > 1:  # several runs: the latest one is the history
        last = steps[-1]["run"]
        steps = [s for s in steps if s["run"] == last]
    return steps


def normalize(history) -> list[dict]:
    """A list of {"action", "args", "result", "error", "state"} from any accepted shape."""
    if isinstance(history, (str, Path)):
        path = Path(history)
        if path.suffix == ".jsonl":
            return _from_trace(path)
        history = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(history, dict):
        history = history.get("messages") or history.get("steps") or []
    history = list(history)
    if any(_get(m, "tool_calls") or _get(m, "tool_call_id") or isinstance(_get(m, "content"), list)
           for m in history if not (isinstance(m, dict) and ("tool" in m or "action" in m))):
        return _from_messages(history)
    steps = []
    for s in history:
        steps.append({"action": str(_get(s, "action", "tool", "name", "tool_name", default="?")),
                      "args": _get(s, "args", "arguments", "input", "tool_input", default=""),
                      "result": _get(s, "result", "output", "observation", default=None),
                      "error": _get(s, "error", default=None), "state": _get(s, "state", default=None)})
    return steps


# --- Signals -----------------------------------------------------------------------------------------

def _short(v, limit: int = TEXT_MAX) -> str:
    t = " ".join(_text(v).split())
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "..."


def _key(v) -> str:
    return hashlib.sha256(_text(v).encode()).hexdigest()[:12] if v not in (None, "") else ""


def _times(n: int) -> str:
    return "once" if n == 1 else "twice" if n == 2 else f"{n} times"


def signals(steps: list[dict], window: int = WINDOW) -> list[dict]:
    """Loop patterns in the last `window` steps, each {"kind", "label", "strength", "attrs"}. Pure counting."""
    recent = steps[-window:]
    n = len(recent)
    out = []
    if not n:
        return out
    calls = [(s["action"], _key(s["args"])) for s in recent]
    outcomes = [_key(s["error"] or s["result"] or s.get("state")) for s in recent]  # a trace's state is its result

    # the same call at the end, again and again
    streak = 1
    while streak < n and calls[-1 - streak] == calls[-1]:
        streak += 1
    if streak >= 2:
        distinct = len({outcomes[-i - 1] for i in range(streak)})
        same = distinct == 1
        how = "the same result each time" if same else             "a different result each time" if distinct == streak else f"{distinct} different results"
        out.append({"kind": "repeat", "strength": streak, "changing": not same,
                    "label": f"{recent[-1]['action']} called {_times(streak)} in a row with the same arguments, {how}",
                    "attrs": {"in_a_row": streak, "same_result_each_time": "yes" if same else "no"}})

    # the same call with the same result many times in the window, not only at the end (a changing result is polling)
    counts: dict = {}
    for c, o in zip(calls, outcomes):
        counts[(c, o)] = counts.get((c, o), 0) + 1
    (call, _), k = max(counts.items(), key=lambda kv: kv[1])
    covered = call == calls[-1] and k <= streak  # already said by the streak above
    if k >= 2 and not covered:
        out.append({"kind": "repeat_total", "strength": k,
                    "label": f"{call[0]} called {_times(k)} with the same arguments and the same result "
                             f"in the last {n} steps", "attrs": {"times": k}})

    # the same error again
    errors = [_short(s["error"], 80) for s in recent if s["error"]]
    if errors:
        top = max(set(errors), key=errors.count)
        k = errors.count(top)
        tail = 0
        while tail < n and recent[-1 - tail]["error"]:
            tail += 1
        out.append({"kind": "errors", "strength": k,
                    "label": f"the same error {_times(k)}: {top}",
                    "attrs": {"errors_in_window": len(errors), "failing_in_a_row": tail}})

    # a cycle: the last p calls repeat the p before them (A B A B, A B C A B C)
    for p in (2, 3, 4):
        reps = 1
        while n >= p * (reps + 1) and calls[n - p * (reps + 1): n - p * reps] == calls[n - p:]:
            reps += 1
        if reps >= 2 and len(set(calls[n - p:])) == p:
            names = " -> ".join(recent[n - p + i]["action"] for i in range(p))
            out.append({"kind": "cycle", "strength": reps * p,
                        "label": f"a cycle repeated {_times(reps)}: {names}", "attrs": {"cycle_length": p}})
            break

    # new information: a result or state not seen before in the window
    seen, new = set(), []
    for s, o in zip(recent, outcomes):
        key = _key(s.get("state")) or o
        new.append(bool(key) and key not in seen)
        seen.add(key)
    last = new[-min(8, n):]
    stale = 0
    while stale < n and not new[-1 - stale]:
        stale += 1
    out.append({"kind": "novelty", "strength": stale,
                "label": f"new information in {sum(last)} of the last {len(last)} steps",
                "attrs": {"steps_since_new_information": stale}})
    return out


def loop_signals(history, window: int = WINDOW) -> list[str]:
    """The loop patterns in plain words, strongest first. Local and free: no Jev call."""
    sigs = [s for s in signals(normalize(history), window)
            if not (s["kind"] == "novelty" and s["strength"] < 2) and not s.get("changing")  # polling is not a loop
            and not (s["kind"] in ("repeat", "repeat_total", "errors") and s["strength"] < MIN_REPEAT)]
    return [s["label"] for s in sorted(sigs, key=lambda s: -s["strength"])]


# --- The adapter -------------------------------------------------------------------------------------

class StepsAdapter(Adapter):
    """Options (a dict: `StepsAdapter({"window": 20, "recent": 6})`):

    window  how many recent steps are searched for loops (default 20)
    recent  how many of the latest steps are sent to Jev one by one (default 6)
    """

    name = "steps"
    version = "1"
    renderer = "table"
    extra = "steps"
    reasons = REASONS

    def __init__(self, config=None):
        register_reasons(REASONS)
        self.config: dict = dict(config or {})

    def configure(self, config) -> None:
        if isinstance(config, (str, Path)):
            config = json.loads(Path(config).read_text(encoding="utf-8"))
        self.config = dict(config or {})

    def extract(self, source, **options) -> Extracted:
        steps = normalize(source)
        if not steps:
            raise ValueError("no steps found. Pass step dicts, chat messages with tool calls, or a jevbrief trace")
        window, recent = int(self.config.get("window", WINDOW)), int(self.config.get("recent", RECENT))
        facts = []
        for s in signals(steps, window):
            facts.append(Fact(id=fact_id("steps", s["kind"]), kind=s["kind"], label=clean_label(s["label"]),
                              attrs=s["attrs"], meta={"strength": s["strength"], "order": len(facts)}))
        for i, s in enumerate(steps):
            age = len(steps) - i
            attrs = {"step": f"{age} steps ago" if age > 1 else "the latest step"}
            if s["args"] not in (None, "", {}):
                attrs["args"] = _short(s["args"], 80)
            if s["error"]:
                attrs["error"] = _short(s["error"])
            elif s["result"] not in (None, ""):
                attrs["result"] = _short(s["result"])
            facts.append(Fact(id=fact_id("steps-step", str(i), s["action"]), kind="step",
                              label=clean_label(s["action"]), attrs=attrs,
                              meta={"age": age, "recent": age <= recent, "order": len(facts)}))
        return Extracted(facts, {"name": Path(source).name if isinstance(source, (str, Path)) else "steps",
                                 "steps": len(steps)})

    def rules(self) -> RuleSet:
        hidden, disabled, unlabeled, _, _ = CORE_RULES

        def weak(f):
            """A call repeated or an error seen fewer than MIN_REPEAT times is normal: a retry, a second look."""
            return f.kind in ("repeat", "repeat_total", "errors") and f.meta["strength"] < MIN_REPEAT

        return RuleSet([
            hidden, disabled, unlabeled,
            Rule(OLD, lambda f, ctx: Drop(OLD) if f.kind == "step" and not f.meta["recent"] else None),
            Rule(WEAK, lambda f, ctx: Drop(WEAK) if f.kind != "step" and weak(f) else None),
            Rule("steps.loop", lambda f, ctx: Boost(0.3, "steps.loop")
                 if f.kind in ("repeat", "repeat_total", "errors", "cycle") else None),
            Rule("steps.recent", lambda f, ctx: Boost(0.1, "steps.recent") if f.kind == "step" else None),
            # No goal_match or duplicate: repeated steps with the same label are the evidence.
        ])

    def packs(self):
        pack = OptionChoice(
            "verdict",
            "Agent goal: {goal}\n"
            "`signals` are loop patterns counted in code over the agent's recent steps, and `steps` are its latest "
            "steps, newest last. Is the agent making progress toward the goal?",
            VERDICTS,
            extra={
                "stuck": {"type": "noul", "instructions":
                          "Agent goal: {goal}\nIs the agent stuck: repeating itself or failing the same way, "
                          "without getting closer to the goal?"},
                "advice": {"type": "choice", "instructions":
                           "Agent goal: {goal}\nWhat should the agent do next?", "criteria": ADVICE},
            },
        )
        return {pack.name: pack}

    def state(self, goal, kept, source):
        return {"goal": goal, "signals": [f.state() for f in kept if f.kind != "step"],
                "steps": [f.state() for f in sorted((f for f in kept if f.kind == "step"), key=lambda f: -f.meta["age"])]}

    def raw(self, facts):
        """What a naive integration sends: every step, oldest first, and no counted signals."""
        return sorted((f for f in facts if f.kind == "step"), key=lambda f: -f.meta["age"])[-254:]


# --- The one-call API --------------------------------------------------------------------------------

@dataclass
class Progress:
    """What `check_progress` returns."""
    stuck: bool | None             # None when Jev's answer is not confident enough to say
    verdict: str | None            # progressing, stuck_repeating, stuck_failing, or done
    advice: str | None             # continue, change_arguments, try_different_tool, ask_user, or stop
    probability: float | None      # Jev's probability that the agent is stuck
    signals: list[str] = field(default_factory=list)   # the loop patterns counted in code
    decision: Decision | None = field(default=None, repr=False)


def check_progress(history, goal: str, *, window: int = WINDOW, recent: int = RECENT,
                   trace: str | None = "traces/progress.jsonl", min_confidence: float = 0.5, **briefing) -> Progress:
    """Ask Jev whether an agent is making progress, from its recent steps. Call it every few steps.

    `history` is step dicts, chat messages with tool calls (OpenAI, Anthropic, LangChain), or a jevbrief trace.
    """
    b = Briefing(StepsAdapter({"window": window, "recent": recent}), goal, trace=trace,
                 min_confidence=min_confidence, **briefing)
    b.extract(history)
    d = b.decide()
    p = (d.answers.get("stuck") or {}).get("noul")
    advice = (d.answers.get("advice") or {}).get("choice")
    verdict = d.choice if d.outcome in ("applied", "reused") else None
    stuck = verdict.startswith("stuck") if verdict else (p > 0.5 if p is not None else None)
    return Progress(stuck, verdict, advice, p, loop_signals(history, window), d)
