"""Fit kept facts into a token and option budget."""

from __future__ import annotations

import json

from .facts import BUDGET, Fact

DEFAULT_TOKENS = 2000
MAX_TOKENS = 30000
DEFAULT_OPTIONS = 60
MAX_OPTIONS = 255 - 1  # one Choice option is reserved for "none"


def estimate_tokens(obj) -> int:
    """Rough token count: compact JSON length / 4. No tokenizer dependency."""
    return -(-len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False)) // 4)


def fit(facts: list[Fact], budget_tokens: int = DEFAULT_TOKENS, max_options: int = DEFAULT_OPTIONS,
        base: dict | None = None) -> int:
    """Mark kept facts that do not fit as `budget`. Returns the estimated tokens used.

    `base` is the rest of the state (goal, url) so its cost counts against the budget.
    """
    if not 0 < budget_tokens <= MAX_TOKENS:
        raise ValueError(f"budget_tokens must be between 1 and {MAX_TOKENS}")
    if not 0 < max_options <= MAX_OPTIONS:
        raise ValueError(f"max_options must be between 1 and {MAX_OPTIONS}")
    used = estimate_tokens(base or {})
    count = 0
    for f in sorted((f for f in facts if f.kept), key=lambda f: (-f.score, f.y)):
        cost = estimate_tokens(f.state()) + 1
        if count >= max_options or used + cost > budget_tokens:
            f.drop(BUDGET)
            continue
        used += cost
        count += 1
    return used
