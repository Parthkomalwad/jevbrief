"""One TraceRecord per decision, stored as JSON Lines."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

LEVELS = ("off", "summary", "full")
OUTCOMES = ("applied", "reused", "low_confidence", "error")


@dataclass
class TraceRecord:
    run_id: str
    tick: int
    source: dict
    goal: str
    facts: list[dict]
    budget: dict
    fingerprint: dict
    jev: dict
    outcome: str
    state: dict | None = None  # only at trace level "full"
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["state"] is None:
            del d["state"]
        return d


def write(path: str | Path, record: TraceRecord) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


def read(path: str | Path) -> list[TraceRecord]:
    with Path(path).open(encoding="utf-8") as f:
        return [TraceRecord(**json.loads(line)) for line in f if line.strip()]
