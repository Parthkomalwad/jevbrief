"""Render a JSONL trace into the single-file HTML viewer."""

from __future__ import annotations

import json
import tempfile
import webbrowser
from importlib.resources import files
from pathlib import Path

PLACEHOLDER = "/*__TRACES__*/[]"


def render(trace_path: str | Path) -> str:
    lines = Path(trace_path).read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    data = json.dumps(records, ensure_ascii=False).replace("</", "<\\/")
    return files("jevbrief").joinpath("viewer.html").read_text(encoding="utf-8").replace(PLACEHOLDER, data)


def open_viewer(trace_path: str | Path, open_browser: bool = True) -> Path:
    out = Path(tempfile.gettempdir()) / f"jevbrief-{Path(trace_path).stem}.html"
    out.write_text(render(trace_path), encoding="utf-8")
    if open_browser:
        webbrowser.open(out.as_uri())
    return out
