"""Tests for the mysource adapter. Copy to tests/test_<name>.py."""

import json

from jevbrief import Briefing
from jevbrief.adapters.mysource import ARCHIVED, MySourceAdapter
from jevbrief.testing import FakeJev, check_adapter

RECORDS = [
    {"id": 1, "title": "Refund for order 1182", "status": "open"},
    {"id": 2, "title": "Old refund", "status": "closed", "archived": True},
    {"id": 3, "title": "", "status": "open"},
]


def sample(tmp_path):
    path = tmp_path / "records.json"
    path.write_text(json.dumps(RECORDS))
    return path


def test_contract(tmp_path):
    check_adapter(MySourceAdapter(), sample(tmp_path), goal="find the refund")


def test_every_reason_code(tmp_path):
    b = Briefing(MySourceAdapter(), "find the refund", trace=None, jev=FakeJev())
    b.extract(sample(tmp_path))
    reasons = [f.reason for f in b.facts]
    assert reasons == ["goal_match", ARCHIVED, "unlabeled"]
