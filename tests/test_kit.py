"""The adapter kit: the base Adapter, config loading, file discovery, options reaching rules, Extracted.raw."""

import pytest

from jevbrief import Briefing, Extracted, Fact
from jevbrief.adapters import Adapter, adapter_rules, get
from jevbrief.bench import _raw
from jevbrief.questions import FactChoice
from jevbrief.rules import Drop, Rule, RuleSet
from jevbrief.sources import find_files, load_config
from jevbrief.testing import FakeJev
from jevbrief.text import frequency, template

TINY_REASONS = {"tiny.small": "Below the size limit"}


class Tiny(Adapter):
    name = "tiny"
    reasons = TINY_REASONS

    def extract(self, source, **options):
        facts = [Fact(id=f"e{n}", kind="item", label=f"item {n}", meta={"n": n}) for n in source]
        return Extracted(facts, raw=[Fact(id="r", kind="line", label="raw line")])

    def rules(self, options=None):
        limit = self.settings(options).get("limit", 0)
        return RuleSet([Rule("tiny.small", lambda f, ctx: Drop("tiny.small") if f.meta["n"] < limit else None)])

    def packs(self):
        return {"pick": FactChoice("pick", "Goal: {goal}")}


def test_base_constructor_registers_reasons_and_loads_config(tmp_path):
    from jevbrief.facts import REASONS

    (tmp_path / "c.toml").write_text('limit = 3\n', encoding="utf-8")
    (tmp_path / "c.json").write_text('{"limit": 4}', encoding="utf-8")
    assert Tiny().config == {} and REASONS["tiny.small"] == "Below the size limit"
    assert Tiny(tmp_path / "c.toml").config == {"limit": 3} and Tiny({"limit": 5}).config == {"limit": 5}
    a = Tiny()
    a.configure(tmp_path / "c.json")
    assert a.config == {"limit": 4} and load_config(None) == {}


def test_extract_options_reach_rules_without_adapter_state():
    b = Briefing(Tiny({"limit": 2}), "g", trace=None, jev=FakeJev())
    b.extract([1, 2, 3])
    assert [f.kept for f in b.facts] == [False, True, True]
    b.extract([1, 2, 3], limit=3)  # a per-call option wins over the config, for this call only
    assert [f.kept for f in b.facts] == [False, False, True]
    b.extract([1, 2, 3])
    assert [f.kept for f in b.facts] == [False, True, True]
    assert not {k for k in vars(b.adapter) if k != "config"}  # nothing else stored on the adapter


def test_old_style_rules_without_options_still_work():
    class Old(Tiny):
        def rules(self):
            return RuleSet([])

    assert adapter_rules(Old(), {"limit": 9}).rules == []
    b = Briefing(Old(), "g", trace=None, jev=FakeJev())
    b.extract([1], limit=9)
    assert b.facts[0].kept


def test_adapters_without_config_reject_one():
    for name in ("web", "nes"):
        try:
            a = get(name)
        except ImportError:
            continue
        with pytest.raises(ValueError, match="takes no config"):
            a.configure({"x": 1})


def test_raw_arm_uses_extracted_raw_when_set():
    a = Tiny()
    b = _raw(a, "g", a.extract([1, 2]), None, FakeJev())
    assert [f.label for f in b.facts] == ["raw line"]


def test_find_files(tmp_path):
    (tmp_path / "sub").mkdir()
    for name in ("b.json", "a.json", "sub/c.jsonl", "skip.txt"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    assert [p.name for p in find_files(tmp_path, (".json", ".jsonl"))] == ["a.json", "b.json", "c.jsonl"]
    assert [p.name for p in find_files([tmp_path / "skip.txt", tmp_path / "a.json"], (".json",))] == ["skip.txt", "a.json"]


def test_text_helpers_are_shared_by_ci_and_otel():
    from jevbrief.adapters import ci, otel

    assert ci.template is template is otel.template and otel.frequency is frequency
    assert template("user 42 from 10.0.0.1 got 503") == "user <n> from <ip> got 503"
