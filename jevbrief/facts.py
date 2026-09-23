"""The Fact record and the registry of reason codes."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

LABEL_MAX = 80

# Core reason codes for dropped facts. Adapters add their own, namespaced as "<adapter>.<code>".
HIDDEN = "hidden"
DISABLED = "disabled"
UNLABELED = "unlabeled"
DUPLICATE = "duplicate"
LOW_SCORE = "low_score"
BUDGET = "budget"

# Every reason and keep-rule name that can appear in `Fact.reason`, with a plain description.
REASONS: dict[str, str] = {
    HIDDEN: "Not observable right now (for web pages: not visible)",
    DISABLED: "Exists but cannot be acted on",
    UNLABELED: "No usable label, so Jev could not tell what it is",
    DUPLICATE: "Same kind and label as a higher-scored fact",
    LOW_SCORE: "Scored below the keep threshold",
    BUDGET: "Would have been kept, cut only to fit the token or option budget",
    "goal_match": "Kept: the label shares a word with the goal",
    "base": "Kept: no rule dropped it",
    "pinned": "Kept: pinned by the caller",
}


def register_reasons(codes: dict[str, str], replace: bool = False) -> None:
    """Add reason codes. Re-registering a code with a different description is an error unless `replace`."""
    for code, text in codes.items():
        if not replace and REASONS.get(code, text) != text:
            raise ValueError(f"reason code {code!r} is already registered with a different description")
        REASONS[code] = text


@dataclass
class Fact:
    id: str
    kind: str
    label: str
    attrs: dict = field(default_factory=dict)  # sent to Jev; values should already be semantic
    meta: dict = field(default_factory=dict)   # never sent to Jev: locators, positions, raw values
    visible: bool = True                       # observable right now
    enabled: bool = True                       # can be acted on
    score: float = 0.0
    kept: bool = True
    reason: str = ""

    def drop(self, reason: str) -> None:
        self.kept = False
        self.reason = reason

    def state(self) -> dict:
        """The compact form sent to Jev."""
        return {"id": self.id, "kind": self.kind, "label": self.label, **self.attrs}

    def to_dict(self, level: str = "full") -> dict:
        if level == "summary":
            return {"id": self.id, "kept": self.kept, "reason": self.reason}
        d = asdict(self)
        d["meta"] = {k: v for k, v in self.meta.items() if k in ("box", "order", "view")}  # small, useful to viewers
        return d

    # Convenience for spatial adapters (web, games).
    @property
    def selector(self) -> str:
        return self.meta.get("selector", "")

    @property
    def box(self) -> list[int] | None:
        return self.meta.get("box")


def fact_id(*parts: str) -> str:
    """Stable ID from identifying parts, so the same thing keeps its ID across ticks."""
    return "e" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:6]


def clean_label(text) -> str:
    return " ".join(str(text or "").split())[:LABEL_MAX]
