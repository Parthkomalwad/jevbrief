import os

import pytest

from jevbrief import Brief, Briefing, OptionChoice, budget
from jevbrief.adapters.web.rules import web_rules
from jevbrief.cli import load_env
from jevbrief.facts import REASONS, Fact, register_reasons
from jevbrief.fingerprint import fingerprint
from jevbrief.jev import Answers
from jevbrief.rules import Boost, Drop, Rule, RuleSet

GOAL = "add this item to the cart"


def F(id, label="Add to cart", kind="button", in_viewport=True, y=0, selector="", **kw):
    return Fact(id=id, kind=kind, label=label, meta={"in_viewport": in_viewport, "y": y, "order": y,
                                                     "selector": selector}, **kw)


def web(facts, goal=GOAL, **kw):
    return web_rules().apply(facts, goal, **kw)


def reasons(facts):
    return {f.id: f.reason for f in facts}


# Web rules (every reason code).

def test_hidden_disabled_unlabeled():
    facts = web([F("a", visible=False), F("b", enabled=False), F("c", label="")])
    assert reasons(facts) == {"a": "hidden", "b": "disabled", "c": "unlabeled"}
    assert not any(f.kept for f in facts)


def test_text_without_goal_word_is_not_interactive():
    facts = web([F("t", "Reviews", kind="text"), F("u", "Your cart", kind="text")])
    assert reasons(facts) == {"t": "web.not_interactive", "u": "goal_match"}


def test_goal_match_and_viewport_scores():
    a, b, c = web([F("a"), F("b", "Home"), F("c", "Home page", in_viewport=False)])
    assert (a.score, a.reason) == (0.95, "goal_match")
    assert (b.score, b.reason) == (0.6, "web.in_viewport")
    assert (c.score, c.reason) == (0.5, "base")


def test_duplicate_keeps_higher_score():
    low, high = web([F("low", in_viewport=False), F("high")])
    assert high.kept and not low.kept and low.reason == "duplicate"


def test_far_below_viewport_is_low_score():
    (f,) = web([F("f", "Careers", in_viewport=False, y=5000)], source={"viewport_h": 800})
    assert f.reason == "low_score"


def test_button_next_to_goal_input_is_boosted():
    email = F("i", "Your email", kind="input", selector="html>footer>input", in_viewport=False, y=5000)
    btn = F("b", "Sign up", selector="html>footer>button", in_viewport=False, y=5000)
    other = F("o", "Careers", kind="link", selector="html>footer>a", in_viewport=False, y=5000)
    web([email, btn, other], "subscribe to the email newsletter")
    assert btn.kept and btn.reason == "web.near_goal_input"
    assert other.reason == "low_score"


def test_pins_force_keep():
    (f,) = web([F("p", visible=False)], pins=["p"])
    assert f.kept and f.reason == "pinned"


# Rule sets are pluggable.

def test_ruleset_without_and_with_rule():
    rs = web_rules().without("web.far_below")
    (f,) = rs.apply([F("f", "Careers", in_viewport=False, y=5000)], GOAL)
    assert f.kept
    register_reasons({"test.no_careers": "No careers links"})
    rs = rs.with_rule(Rule("test.no_careers", lambda f, ctx: Drop("test.no_careers") if "Careers" in f.label else None),
                      before="goal_match")
    (f,) = rs.apply([F("f", "Careers")], GOAL)
    assert f.reason == "test.no_careers"


def test_named_boost_becomes_keep_reason():
    rs = RuleSet([Rule("test.vip", lambda f, ctx: Boost(0.2, "test.vip"))])
    (f,) = rs.apply([F("f", "Anything")], GOAL)
    assert (f.score, f.reason) == (0.7, "test.vip")


def test_register_reasons_rejects_conflicts():
    register_reasons({"test.same": "One"})
    register_reasons({"test.same": "One"})
    with pytest.raises(ValueError):
        register_reasons({"test.same": "Two"})
    assert REASONS["test.same"] == "One"


# Budget and fingerprint.

def test_budget_cuts_by_option_cap_and_tokens():
    facts = web([F(f"e{i}", f"Add item {i}") for i in range(10)])
    budget.fit(facts, max_options=4)
    assert sum(f.kept for f in facts) == 4
    assert {f.reason for f in facts if not f.kept} == {"budget"}

    facts = web([F(f"e{i}", f"Add item {i}") for i in range(10)])
    used = budget.fit(facts, budget_tokens=40)
    assert used <= 40 and 0 < sum(f.kept for f in facts) < 10


def test_budget_limits_are_enforced():
    with pytest.raises(ValueError):
        budget.fit([], budget_tokens=30001)
    with pytest.raises(ValueError):
        budget.fit([], max_options=255)


def test_fingerprint_is_order_independent_and_goal_sensitive():
    a, b = F("a"), F("b", "View cart")
    assert fingerprint([a, b], GOAL) == fingerprint([b, a], GOAL)
    assert fingerprint([a, b], GOAL) != fingerprint([a, b], "sign in")


# Decisions.

class FakeJev:
    model = "jev-test"

    def __init__(self, choice="a", confidence=0.9, fail=False):
        self.calls, self.choice_id, self.conf, self.fail = 0, choice, confidence, fail

    def ask(self, state, questions):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        q = questions["next_click"]
        assert "none" in q["criteria"] and set(q["criteria"]) - {"none"} == {e["id"] for e in state["elements"]}
        return Answers("jev-test", {"next_click": {"type": "choice", "choice": self.choice_id, "confidence": self.conf,
                                                   "probabilities": {self.choice_id: self.conf}}}, 5, 100)


def brief_with(jev, tmp_path, **kw):
    b = Brief(GOAL, trace=str(tmp_path / "t.jsonl"), jev=jev, **kw)
    b.load([F("a"), F("b", "View cart"), F("h", visible=False)], {"url": "file://shop"})
    return b


def test_applied_then_reused_when_state_unchanged(tmp_path):
    jev = FakeJev()
    b = brief_with(jev, tmp_path)
    d1 = b.next_click()
    assert d1.outcome == "applied" and d1.fact.id == "a"
    d2 = b.next_click()
    assert d2.outcome == "reused" and d2.fact.id == "a" and jev.calls == 1
    assert d2.record.fingerprint == {"hash": d1.record.fingerprint["hash"], "changed": False, "reused_tick": 1}
    b.load([F("a"), F("c", "Checkout")], {"url": "file://shop"})
    assert b.next_click().outcome == "applied" and jev.calls == 2


def test_low_confidence_and_none_take_no_action(tmp_path):
    assert brief_with(FakeJev(confidence=0.3), tmp_path).next_click().fact is None
    d = brief_with(FakeJev(choice="none"), tmp_path).next_click()
    assert d.outcome == "low_confidence" and d.fact is None


def test_error_is_recorded(tmp_path):
    d = brief_with(FakeJev(fail=True), tmp_path).next_click()
    assert d.outcome == "error" and d.fact is None and "boom" in d.record.jev["error"]


def test_trace_record_has_schema_adapter_and_reason_legend(tmp_path):
    d = brief_with(FakeJev(), tmp_path).next_click()
    r = d.record
    assert r.schema == 1 and r.adapter["name"] == "web"
    assert all(f["reason"] for f in r.facts if not f["kept"])
    assert r.reasons["hidden"] and r.reasons["goal_match"]


def test_option_choice_pack_decides_without_a_fact(tmp_path):
    class ActionJev(FakeJev):
        def ask(self, state, questions):
            assert set(questions["next_action"]["criteria"]) == {"jump", "wait"}
            return Answers("jev-test", {"next_action": {"type": "choice", "choice": "jump", "confidence": 0.8}}, 5)

    pack = OptionChoice("next_action", "Goal: {goal}", {"jump": "Jump now", "wait": "Do nothing"})
    b = Brief(GOAL, trace=None, jev=ActionJev(), pack=pack)
    b.load([F("a")])
    d = b.decide()
    assert (d.outcome, d.choice, d.fact) == ("applied", "jump", None)


def test_briefing_rejects_bad_trace_level():
    from jevbrief.adapters.web import WebAdapter

    with pytest.raises(ValueError):
        Briefing(WebAdapter(), GOAL, trace_level="loud")


def test_load_env_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("JB_A=from_file\nJB_B='quoted'\n# c\nJB_EMPTY=\n")
    monkeypatch.setenv("JB_A", "from_env")
    monkeypatch.delenv("JB_B", raising=False)
    monkeypatch.delenv("JB_EMPTY", raising=False)
    load_env(env)
    assert os.environ["JB_A"] == "from_env" and os.environ["JB_B"] == "quoted" and "JB_EMPTY" not in os.environ


def test_rules_see_config_and_options_given_at_extract_time():
    """Regression: rules were built when the Briefing was created, so config or options passed to
    `extract()` were silently ignored."""
    from pathlib import Path

    from jevbrief.adapters.json import JsonAdapter
    from jevbrief.adapters.otel import OtelAdapter
    from jevbrief.testing import FakeJev

    bench = Path(__file__).resolve().parent.parent / "bench"
    by_ctor = Briefing(JsonAdapter(bench / "json" / "tickets.toml"), "billed twice", trace=None, jev=FakeJev())
    by_ctor.extract(bench / "json" / "tickets.json")
    at_extract = Briefing(JsonAdapter(), "billed twice", trace=None, jev=FakeJev())
    at_extract.extract(bench / "json" / "tickets.json", config=bench / "json" / "tickets.toml")
    assert [(f.id, f.reason) for f in at_extract.facts] == [(f.id, f.reason) for f in by_ctor.facts]

    logs = bench / "otel" / "checkout_500.json"
    by_ctor = Briefing(OtelAdapter({"min_severity": "error"}), "checkout", trace=None, jev=FakeJev())
    by_ctor.extract(logs)
    by_option = Briefing(OtelAdapter(), "checkout", trace=None, jev=FakeJev())
    by_option.extract(logs, min_severity="error")
    assert [f.reason for f in by_option.facts] == [f.reason for f in by_ctor.facts]
    default = Briefing(OtelAdapter(), "checkout", trace=None, jev=FakeJev())
    default.extract(logs)
    assert len(by_option.kept) < len(default.kept)  # the option really changed something


def test_rules_passed_to_briefing_are_kept_after_extract():
    from jevbrief.adapters.otel import OtelAdapter
    from jevbrief.testing import FakeJev

    own = RuleSet([])
    b = Briefing(OtelAdapter(), "checkout", rules=own, trace=None, jev=FakeJev())
    b.extract(__import__("pathlib").Path(__file__).resolve().parent.parent / "bench" / "otel" / "checkout_500.json")
    assert b.rules is own and all(f.kept or f.reason == "budget" for f in b.facts)
