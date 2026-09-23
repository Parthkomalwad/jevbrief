"""The web output (facts, scores, reasons) must stay identical. See make_web_snapshot.py."""

import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from make_web_snapshot import SNAPSHOT, current, run  # noqa: E402


def test_web_output_matches_snapshot():
    assert run(current) == json.loads(Path(SNAPSHOT).read_text(encoding="utf-8"))
