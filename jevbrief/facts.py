"""The Fact record and the reason codes used when a fact is dropped."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

KINDS = ("button", "link", "input", "select", "text")

# Reason codes for dropped facts.
HIDDEN = "hidden"
DISABLED = "disabled"
NOT_INTERACTIVE = "not_interactive"
UNLABELED = "unlabeled"
DUPLICATE = "duplicate"
LOW_SCORE = "low_score"
BUDGET = "budget"
DROP_REASONS = (HIDDEN, DISABLED, NOT_INTERACTIVE, UNLABELED, DUPLICATE, LOW_SCORE, BUDGET)

LABEL_MAX = 80


@dataclass
class Fact:
    id: str
    kind: str
    label: str
    attrs: dict = field(default_factory=dict)
    visible: bool = True
    enabled: bool = True
    in_viewport: bool = False
    y: int = 0
    score: float = 0.0
    kept: bool = True
    reason: str = ""
    selector: str = field(default="", repr=False)  # internal, used to click the element
    box: list[int] | None = None  # [x, y, width, height] in viewport pixels, for the viewer

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
        d.pop("selector")
        return d


def fact_id(tag: str, label: str, path: str) -> str:
    """Stable ID from tag, label, and DOM path, so an element keeps its ID across ticks."""
    return "e" + hashlib.sha256(f"{tag}|{label}|{path}".encode()).hexdigest()[:6]


def clean_label(text: str | None) -> str:
    return " ".join((text or "").split())[:LABEL_MAX]
