"""Deterministic salience scoring. Every dropped fact gets a reason code."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .facts import DISABLED, DUPLICATE, HIDDEN, LOW_SCORE, NOT_INTERACTIVE, UNLABELED, Fact

BASE = 0.5
GOAL_MATCH = 0.35
NEAR_GOAL = 0.20
IN_VIEWPORT = 0.10
FAR_BELOW = -0.25
FAR_SCREENS = 3
KEEP_THRESHOLD = 0.3

STOPWORDS = set(
    "a an the this that these those to of for in on at by with and or but is are be it its "
    "my me i you your we our please then from into up so as".split()
)


def _words(text: str) -> set[str]:
    return {w.rstrip("s") or w for w in re.findall(r"[a-z0-9]+", text.lower())}


def _parent(f: Fact) -> str:
    return f.selector.rsplit(">", 1)[0] if f.selector else ""


def goal_words(goal: str) -> set[str]:
    return {w for w in _words(goal) if w not in STOPWORDS}


def score(facts: list[Fact], goal: str, pins: Iterable[str] = (), viewport_h: int = 800) -> list[Fact]:
    """Score facts in place and mark drops. Returns the same list."""
    pins = set(pins)
    words = goal_words(goal)

    for f in facts:
        f.kept, f.reason, f.score = True, "", BASE
        if f.id in pins:
            f.score, f.reason = 1.0, "pinned"
            continue
        if not f.visible:
            f.drop(HIDDEN)
            continue
        if not f.enabled:
            f.drop(DISABLED)
            continue
        if not f.label:
            f.drop(UNLABELED)
            continue
        match = bool(words & _words(f.label))
        if f.kind == "text" and not match:
            f.drop(NOT_INTERACTIVE)
            continue
        rules = []
        if match:
            f.score += GOAL_MATCH
            rules.append("goal_match")
        if f.in_viewport:
            f.score += IN_VIEWPORT
            rules.append("in_viewport")
        if f.y > FAR_SCREENS * viewport_h:
            f.score += FAR_BELOW
        f.score = round(f.score, 4)
        f.reason = rules[0] if rules else "base"

    # A button next to a goal-matching input (same parent element) is likely its submit button.
    goal_inputs = {_parent(f) for f in facts if f.kept and f.kind == "input" and f.reason == "goal_match"}
    for f in facts:
        if f.kept and f.kind == "button" and f.reason not in ("goal_match", "pinned") and _parent(f) in goal_inputs:
            f.score = round(f.score + NEAR_GOAL, 4)
            f.reason = "near_goal_input"

    seen: dict[tuple[str, str], Fact] = {}
    for f in sorted((f for f in facts if f.kept), key=lambda f: -f.score):
        key = (f.kind, f.label.lower())
        if key in seen and f.reason != "pinned":
            f.drop(DUPLICATE)
        else:
            seen[key] = f

    for f in facts:
        if f.kept and f.score < KEEP_THRESHOLD:
            f.drop(LOW_SCORE)
    return facts
