"""Question packs: build Jev questions from the kept facts, and turn answers into a choice.

Questions are plain dicts in the TypeSafe API shape, so they can be written to traces:
    {"type": "choice", "instructions": ..., "criteria": {option: description}}
    {"type": "noul", "instructions": ..., "criteria": {"true": ..., "false": ...}}   # criteria optional
    {"type": "score", "instructions": ..., "criteria": [level, level, ...]}
"""

from __future__ import annotations

from collections.abc import Callable

from .facts import Fact

NONE = "none"
NONE_TEXT = "None of these fits the goal"


class QuestionPack:
    """Base class. `primary` names the question whose answer drives the decision."""

    name = "pack"
    primary = "choice"

    def build(self, goal: str, kept: list[Fact], state: dict) -> dict[str, dict]:
        raise NotImplementedError

    def fact_for(self, choice: str, kept: list[Fact]) -> Fact | None:
        """The fact behind a chosen option, if the options are facts."""
        return None


class FactChoice(QuestionPack):
    """One Choice whose options are the kept facts' IDs, plus `none`.

    `instructions` is a template with `{goal}`. `describe(fact)` gives each option's description.
    `extra` adds independent questions (for example a Noul) to the same call, as in TypeSafe's fan-out pattern.
    """

    def __init__(self, qid: str, instructions: str, describe: Callable[[Fact], str] | None = None,
                 none_text: str = NONE_TEXT, extra: dict[str, dict] | None = None):
        self.name = self.primary = qid
        self.instructions = instructions
        self.describe = describe or (lambda f: f"{f.kind}: {f.label}")
        self.none_text = none_text
        self.extra = extra or {}

    def build(self, goal, kept, state):
        criteria = {f.id: self.describe(f) for f in kept}
        criteria[NONE] = self.none_text
        return {self.primary: {"type": "choice", "instructions": self.instructions.format(goal=goal),
                               "criteria": criteria}, **_fill(self.extra, goal)}

    def fact_for(self, choice, kept):
        return next((f for f in kept if f.id == choice), None)


class OptionChoice(QuestionPack):
    """One Choice over a fixed set of options (for example game actions), described in `options`."""

    def __init__(self, qid: str, instructions: str, options: dict[str, str], extra: dict[str, dict] | None = None):
        self.name = self.primary = qid
        self.instructions = instructions
        self.options = dict(options)
        self.extra = extra or {}

    def build(self, goal, kept, state):
        return {self.primary: {"type": "choice", "instructions": self.instructions.format(goal=goal),
                               "criteria": dict(self.options)}, **_fill(self.extra, goal)}


def _fill(questions: dict[str, dict], goal: str) -> dict[str, dict]:
    out = {}
    for qid, q in questions.items():
        q = dict(q)
        if isinstance(q.get("instructions"), str):
            q["instructions"] = q["instructions"].format(goal=goal)
        out[qid] = q
    return out
