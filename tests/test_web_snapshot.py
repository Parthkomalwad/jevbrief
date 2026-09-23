"""The web adapter must reproduce the pre-refactor output exactly (see make_web_snapshot.py)."""

import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from make_web_snapshot import SNAPSHOT, run  # noqa: E402

# Reason codes that were renamed when the web rules moved into the web adapter.
RENAMED = {"not_interactive": "web.not_interactive", "in_viewport": "web.in_viewport",
           "near_goal_input": "web.near_goal_input"}


def refactored(page, goal, budget):
    from jevbrief import Brief

    brief = Brief(goal, budget_tokens=budget, trace=None, screenshot=False)
    brief.from_page_sync(page)
    return brief.facts


def test_web_output_matches_pre_refactor_snapshot():
    expected = json.loads(Path(SNAPSHOT).read_text(encoding="utf-8"))
    for case in expected:
        for f in case["facts"]:
            f[5] = RENAMED.get(f[5], f[5])
    assert run(refactored, None) == expected
