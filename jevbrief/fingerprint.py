"""Stable hash of the kept state, used to skip Jev calls when nothing changed."""

from __future__ import annotations

import hashlib
import json

from .facts import Fact


def fingerprint(kept: list[Fact], goal: str) -> str:
    payload = {"goal": goal, "facts": sorted((f.state() for f in kept), key=lambda s: s["id"])}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
