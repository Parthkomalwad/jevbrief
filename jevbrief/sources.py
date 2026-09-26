"""Helpers for reading adapter input and config: files and folders, and TOML or JSON config files."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path


def load_config(config, extra: str = "") -> dict:
    """A config from a dict, a `.json` file, or a `.toml` file. None gives an empty config.

    On Python 3.10, TOML needs `tomli`, installed by the adapter's extra (`extra`).
    """
    if config is None:
        return {}
    if isinstance(config, dict):
        return dict(config)
    path = Path(config)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        from .adapters import need

        need(extra or "all", "tomli")
        import tomli as tomllib
    return tomllib.loads(text)


def find_files(source, suffixes: Iterable[str]) -> list[Path]:
    """Paths from a path or a list of paths. Folders are searched recursively for files with `suffixes`,
    in sorted order. Files named directly are returned whatever their suffix."""
    wanted = set(suffixes)
    out: list[Path] = []
    for p in map(Path, source if isinstance(source, (list, tuple)) else [source]):
        out += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix in wanted) if p.is_dir() else [p]
    return out
