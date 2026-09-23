"""Pluggable salience rules. Every dropped fact gets a registered reason code.

A RuleSet runs in three passes:
1. Fact rules, in order. A rule returns Drop (stop), Boost (change the score), or None.
2. Group rules, in order. They see all facts and can boost or drop (for example, duplicates).
3. The keep threshold: kept facts scoring below it are dropped as `low_score`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from .facts import DISABLED, DUPLICATE, HIDDEN, LOW_SCORE, UNLABELED, Fact, register_reasons

BASE = 0.5
KEEP_THRESHOLD = 0.3
GOAL_MATCH = 0.35

STOPWORDS = set(
    "a an the this that these those to of for in on at by with and or but is are be it its "
    "my me i you your we our please then from into up so as".split()
)


def words(text: str) -> set[str]:
    return {w.rstrip("s") or w for w in re.findall(r"[a-z0-9]+", str(text).lower())}


def goal_words(goal: str) -> set[str]:
    return {w for w in words(goal) if w not in STOPWORDS}


@dataclass
class Context:
    goal: str
    goal_words: set[str]
    source: dict = field(default_factory=dict)  # adapter context, for example {"viewport_h": 800}

    def matches(self, text: str) -> bool:
        return bool(self.goal_words & words(text))


@dataclass
class Drop:
    reason: str


@dataclass
class Boost:
    delta: float
    name: str = ""  # a positive boost with a name can become the fact's keep reason


@dataclass
class Rule:
    """A per-fact rule: fn(fact, ctx) -> Drop | Boost | None."""
    name: str
    fn: Callable[[Fact, Context], Drop | Boost | None]
    description: str = ""


@dataclass
class GroupRule:
    """A rule over all facts: fn(facts, ctx) changes scores, reasons, or drops in place."""
    name: str
    fn: Callable[[list[Fact], Context], None]
    description: str = ""


class RuleSet:
    def __init__(self, rules: Iterable[Rule | GroupRule] = (), threshold: float = KEEP_THRESHOLD):
        self.rules = list(rules)
        self.threshold = threshold
        register_reasons({r.name: r.description for r in self.rules if r.description})

    def names(self) -> list[str]:
        return [r.name for r in self.rules]

    def without(self, *names: str) -> RuleSet:
        return RuleSet([r for r in self.rules if r.name not in names], self.threshold)

    def with_rule(self, rule: Rule | GroupRule, before: str | None = None) -> RuleSet:
        rules = list(self.rules)
        idx = self.names().index(before) if before else len(rules)
        rules.insert(idx, rule)
        return RuleSet(rules, self.threshold)

    def apply(self, facts: list[Fact], goal: str, pins: Iterable[str] = (), source: dict | None = None) -> list[Fact]:
        """Score facts in place and mark drops. Returns the same list."""
        ctx = Context(goal, goal_words(goal), source or {})
        pins = set(pins)
        fact_rules = [r for r in self.rules if isinstance(r, Rule)]
        for f in facts:
            f.kept, f.reason, f.score = True, "", BASE
            if f.id in pins:
                f.score, f.reason = 1.0, "pinned"
                continue
            kept_by = []
            for rule in fact_rules:
                result = rule.fn(f, ctx)
                if isinstance(result, Drop):
                    f.drop(result.reason)
                    break
                if isinstance(result, Boost):
                    f.score += result.delta
                    if result.delta > 0 and result.name:
                        kept_by.append(result.name)
            if f.kept:
                f.score = round(f.score, 4)
                f.reason = kept_by[0] if kept_by else "base"
        for rule in self.rules:
            if isinstance(rule, GroupRule):
                rule.fn(facts, ctx)
        for f in facts:
            if f.kept and f.reason != "pinned" and f.score < self.threshold:
                f.drop(LOW_SCORE)
        return facts


# Core rules, usable by any adapter.

hidden = Rule(HIDDEN, lambda f, ctx: Drop(HIDDEN) if not f.visible else None)
disabled = Rule(DISABLED, lambda f, ctx: Drop(DISABLED) if not f.enabled else None)
unlabeled = Rule(UNLABELED, lambda f, ctx: Drop(UNLABELED) if not f.label else None)
goal_match = Rule("goal_match", lambda f, ctx: Boost(GOAL_MATCH, "goal_match") if ctx.matches(f.label) else None)


def _duplicates(facts: list[Fact], ctx: Context) -> None:
    seen: set[tuple[str, str]] = set()
    for f in sorted((f for f in facts if f.kept), key=lambda f: -f.score):
        key = (f.kind, f.label.lower())
        if key in seen and f.reason != "pinned":
            f.drop(DUPLICATE)
        else:
            seen.add(key)


duplicate = GroupRule(DUPLICATE, _duplicates)

CORE_RULES = [hidden, disabled, unlabeled, goal_match, duplicate]
