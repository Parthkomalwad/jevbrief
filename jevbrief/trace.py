"""One TraceRecord per decision, stored as JSON Lines. Images go in a folder next to the trace."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
LEVELS = ("off", "summary", "full")
OUTCOMES = ("applied", "reused", "low_confidence", "error")


@dataclass
class TraceRecord:
    run_id: str
    tick: int
    adapter: dict          # {"name", "version", "renderer"}
    source: dict           # adapter context without large data, for example {"url": ...}
    goal: str
    facts: list[dict]
    budget: dict
    fingerprint: dict
    jev: dict              # the primary question's answer, plus model, latency, tokens, error
    outcome: str
    answers: dict = field(default_factory=dict)    # every question asked in this call
    questions: dict = field(default_factory=dict)  # at level "full": the questions sent
    reasons: dict = field(default_factory=dict)    # description of every reason code used in `facts`
    image: dict | None = None                       # {"path", "width", "height"}, path relative to the trace file
    state: dict | None = None                       # at level "full": the state sent to Jev
    schema: int = SCHEMA
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None and v != {} or k in ("jev", "budget")}


def write(path: str | Path, record: TraceRecord, image: bytes | None = None, ext: str = "jpg") -> None:
    """Append a record. If `image` is given, save it to `<trace>.assets/` and link it from the record."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if image is not None and record.image is not None:
        assets = path.with_suffix(".assets")
        assets.mkdir(exist_ok=True)
        name = f"{record.run_id}-{record.tick}.{ext}"
        (assets / name).write_bytes(image)
        record.image["path"] = f"{assets.name}/{name}"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


def read(path: str | Path) -> list[TraceRecord]:
    names = {f.name for f in fields(TraceRecord)}
    out = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                d.setdefault("adapter", {})
                out.append(TraceRecord(**{k: v for k, v in d.items() if k in names}))
    return out
