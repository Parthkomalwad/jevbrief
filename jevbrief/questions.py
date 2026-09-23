"""The next_click Choice question and mapping its answer back to a Fact."""

from __future__ import annotations

from .facts import Fact

QUESTION = "next_click"
NONE = "none"


def describe(f: Fact) -> str:
    extra = ", ".join(f"{k}={v}" for k, v in f.attrs.items() if k in ("type", "href_path"))
    return f"{f.kind}: {f.label}" + (f" ({extra})" if extra else "")


def state(goal: str, url: str, kept: list[Fact]) -> dict:
    return {"goal": goal, "url": url, "elements": [f.state() for f in kept]}


def next_click(goal: str, kept: list[Fact]) -> dict:
    """Question fields for one Choice. Option keys are fact IDs, plus a `none` option."""
    criteria = {f.id: describe(f) for f in kept}
    criteria[NONE] = "None of these elements helps with the goal"
    return {
        "instructions": (
            f"Goal: {goal}\n"
            "Which one element from `elements` should be clicked or focused next to make progress on this goal?"
        ),
        "criteria": criteria,
    }


def answer_fact(choice: str, kept: list[Fact]) -> Fact | None:
    return next((f for f in kept if f.id == choice), None)
