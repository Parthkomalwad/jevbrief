"""Salience rules for web pages."""

from __future__ import annotations

from ...facts import Fact
from ...rules import CORE_RULES, Boost, Context, Drop, GroupRule, Rule, RuleSet

IN_VIEWPORT = 0.10
FAR_BELOW = -0.25
FAR_SCREENS = 3
NEAR_GOAL = 0.20

NOT_INTERACTIVE = "web.not_interactive"

REASONS = {
    NOT_INTERACTIVE: "Plain text (a heading) with no link to the goal",
    "web.in_viewport": "Kept: visible on screen",
    "web.near_goal_input": "Kept: a button next to a field that matches the goal",
    "web.far_below": "Far below the visible screen (score lowered)",
}

not_interactive = Rule(NOT_INTERACTIVE, lambda f, ctx: Drop(NOT_INTERACTIVE)
                       if f.kind == "text" and not ctx.matches(f.label) else None)
in_viewport = Rule("web.in_viewport", lambda f, ctx: Boost(IN_VIEWPORT, "web.in_viewport")
                   if f.meta.get("in_viewport") else None)
far_below = Rule("web.far_below", lambda f, ctx: Boost(FAR_BELOW)
                 if f.meta.get("y", 0) > FAR_SCREENS * ctx.source.get("viewport_h", 800) else None)


def _parent(f: Fact) -> str:
    return f.selector.rsplit(">", 1)[0] if f.selector else ""


def _near_goal_input(facts: list[Fact], ctx: Context) -> None:
    """A button in the same parent element as a goal-matching input is likely its submit button."""
    parents = {_parent(f) for f in facts if f.kept and f.kind == "input" and f.reason == "goal_match"}
    for f in facts:
        if f.kept and f.kind == "button" and f.reason not in ("goal_match", "pinned") and _parent(f) in parents:
            f.score = round(f.score + NEAR_GOAL, 4)
            f.reason = "web.near_goal_input"


near_goal_input = GroupRule("web.near_goal_input", _near_goal_input)


def web_rules() -> RuleSet:
    hidden, disabled, unlabeled, goal_match, duplicate = CORE_RULES
    return RuleSet([hidden, disabled, unlabeled, not_interactive, goal_match, in_viewport, far_below,
                    near_goal_input, duplicate])
