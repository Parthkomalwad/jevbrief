"""Text helpers shared by adapters: message templates and frequency words."""

from __future__ import annotations

import re
from collections.abc import Callable


def _number(m: re.Match) -> str:
    # Bare 3-digit status codes (100-599) carry meaning ("503"), so they stay. Other numbers become <n>.
    return m.group(0) if re.fullmatch(r"[1-5]\d\d", m.group(0)) else "<n>"


_SUBS: list[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]] = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<id>"),
    (re.compile(r"\b[0-9a-f]{12,}\b", re.I), "<id>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "<email>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\d+(?:\.\d+)?(?:ms|s|m|h|%|kb|mb|gb)?\b", re.I), _number),
]


def template(body: str) -> str:
    """Replace IDs, emails, addresses, and numbers so repeated messages group together."""
    t = str(body)
    for pattern, repl in _SUBS:
        t = pattern.sub(repl, t)
    return " ".join(t.split())


def frequency(count: int) -> str:
    """A count as a word: once, a few times, often, very often."""
    return "once" if count == 1 else "a few times" if count < 10 else "often" if count < 100 else "very often"
