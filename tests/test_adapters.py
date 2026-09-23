from pathlib import Path

import pytest

from jevbrief import Briefing, adapters
from jevbrief.adapters.json import JsonAdapter
from jevbrief.testing import FakeJev, check_adapter

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench" / "json"


def test_builtin_adapters_are_listed():
    assert {"web", "json"} <= set(adapters.available())
    with pytest.raises(ValueError, match="unknown adapter"):
        adapters.get("nope")


def test_web_adapter_contract():
    pytest.importorskip("playwright.sync_api")
    check_adapter(adapters.get("web"), ROOT / "tests" / "pages" / "shop.html", goal="add this item to the cart")


def test_json_adapter_contract():
    check_adapter(JsonAdapter(BENCH / "tickets.toml"), BENCH / "tickets.json", goal="a customer was billed twice")
    check_adapter(JsonAdapter(BENCH / "catalog.toml"), BENCH / "catalog.json", goal="a rain jacket")


def brief(config, data, goal="anything"):
    a = JsonAdapter(config)
    b = Briefing(a, goal, trace=None, jev=FakeJev())
    b.extract(data)
    return b


DATA = {"rows": [
    {"id": 1, "name": "Alpha", "status": "open", "amount": 20, "when": "2026-09-20T00:00:00Z", "tags": ["billing"]},
    {"id": 2, "name": "Beta", "status": "closed", "amount": 500, "when": "2026-09-23T00:00:00Z"},
    {"id": 3, "name": "Gamma", "status": "open", "amount": 900, "when": "2026-01-01T00:00:00Z"},
    {"id": 4, "status": "open"},
    {"id": 5, "name": "Delta", "status": "open"},
]}
CONFIG = {
    "items": "rows", "id": "r{id}", "label": "{name}", "kind": "row", "send": ["status"],
    "required": ["amount"], "match_fields": ["tags"], "now": "2026-09-24T00:00:00Z",
    "buckets": {"size": {"field": "amount", "edges": [100, 800], "labels": ["small", "medium", "large"]},
                "age": {"field": "when", "age": True, "edges": [7], "labels": ["this week", "older"]}},
    "rules": [{"name": "closed", "description": "Closed", "drop_if": {"field": "status", "equals": "closed"}},
              {"name": "old", "description": "Old", "drop_if": {"field": "when", "older_than_days": 90}}],
}


def test_json_rules_buckets_and_reasons():
    b = brief(CONFIG, DATA, goal="a billing question")
    by = {f.id: f for f in b.facts}
    assert by["r2"].reason == "json.closed"
    assert by["r3"].reason == "json.old"
    assert by["r4"].reason == "unlabeled"
    assert by["r5"].reason == "json.missing_field"
    assert by["r1"].kept and by["r1"].reason == "json.goal_match_fields"
    assert by["r1"].attrs == {"status": "open", "size": "small", "age": "this week"}


def test_json_state_has_no_raw_numbers_or_dates_unless_sent():
    b = brief(CONFIG, DATA)
    item = b.state()["items"][0]
    assert "amount" not in item and "when" not in item


def test_json_fixed_options_pack():
    config = {**CONFIG, "question": {"instructions": "Goal: {goal}", "options": {"refund": "Refund", "escalate": "Escalate"}}}
    b = brief(config, DATA)
    q = b.pack.build("g", b.kept, b.state())
    assert b.pack.primary == "choose_option" and set(q["choose_option"]["criteria"]) == {"refund", "escalate"}


def test_json_errors_are_clear(tmp_path):
    with pytest.raises(ValueError, match="needs a config"):
        JsonAdapter().extract(DATA)
    with pytest.raises(ValueError, match="does not point to a list"):
        JsonAdapter({**CONFIG, "items": "missing"}).extract(DATA)
    with pytest.raises(ValueError, match="duplicate IDs"):
        JsonAdapter({**CONFIG, "id": "{status}"}).extract(DATA)
    with pytest.raises(ValueError, match="no operator"):
        brief({**CONFIG, "rules": [{"name": "x", "drop_if": {"field": "status"}}]}, DATA)


def test_web_adapter_rejects_a_config():
    with pytest.raises(ValueError, match="takes no config"):
        adapters.get("web").configure("x.toml")


def test_core_does_not_import_adapters():
    import subprocess
    import sys

    code = "import sys, jevbrief; print(any(m.startswith('jevbrief.adapters.') for m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    assert out == "False"
