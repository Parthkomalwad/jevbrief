import pytest

from jevbrief import Brief, budget, salience
from jevbrief.cli import load_env
from jevbrief.facts import Fact
from jevbrief.fingerprint import fingerprint
from jevbrief.jev import ChoiceResult

GOAL = "add this item to the cart"


def F(id, label="Add to cart", kind="button", **kw):
    kw.setdefault("in_viewport", True)
    return Fact(id=id, kind=kind, label=label, **kw)


def reasons(facts):
    return {f.id: f.reason for f in facts}


def test_hidden_disabled_unlabeled():
    facts = salience.score([F("a", visible=False), F("b", enabled=False), F("c", label="")], GOAL)
    assert reasons(facts) == {"a": "hidden", "b": "disabled", "c": "unlabeled"}
    assert not any(f.kept for f in facts)


def test_text_without_goal_word_is_not_interactive():
    facts = salience.score([F("t", "Reviews", kind="text"), F("u", "Your cart", kind="text")], GOAL)
    assert reasons(facts) == {"t": "not_interactive", "u": "goal_match"}


def test_goal_match_and_viewport_scores():
    a, b, c = salience.score([F("a"), F("b", "Home"), F("c", "Home page", in_viewport=False)], GOAL)
    assert (a.score, a.reason) == (0.95, "goal_match")
    assert (b.score, b.reason) == (0.6, "in_viewport")
    assert (c.score, c.reason) == (0.5, "base")


def test_duplicate_keeps_higher_score():
    low, high = salience.score([F("low", in_viewport=False), F("high")], GOAL)
    assert high.kept and not low.kept and low.reason == "duplicate"


def test_far_below_viewport_is_low_score():
    (f,) = salience.score([F("f", "Careers", in_viewport=False, y=5000)], GOAL, viewport_h=800)
    assert f.reason == "low_score" and f.score < salience.KEEP_THRESHOLD


def test_button_next_to_goal_input_is_boosted():
    email = F("i", "Your email", kind="input", selector="html>footer>input", in_viewport=False, y=5000)
    btn = F("b", "Sign up", selector="html>footer>button", in_viewport=False, y=5000)
    other = F("o", "Careers", kind="link", selector="html>footer>a", in_viewport=False, y=5000)
    salience.score([email, btn, other], "subscribe to the email newsletter")
    assert btn.kept and btn.reason == "near_goal_input"
    assert other.reason == "low_score"


def test_pins_force_keep():
    (f,) = salience.score([F("p", visible=False)], GOAL, pins=["p"])
    assert f.kept and f.reason == "pinned"


def test_budget_cuts_by_option_cap_and_tokens():
    facts = salience.score([F(f"e{i}", f"Add item {i}") for i in range(10)], GOAL)
    budget.fit(facts, max_options=4)
    assert sum(f.kept for f in facts) == 4
    assert {f.reason for f in facts if not f.kept} == {"budget"}

    facts = salience.score([F(f"e{i}", f"Add item {i}") for i in range(10)], GOAL)
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


class FakeJev:
    model = "jev-test"

    def __init__(self, choice="a", confidence=0.9, fail=False):
        self.calls, self.choice_id, self.conf, self.fail = 0, choice, confidence, fail

    def choice(self, state, qid, instructions, criteria):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        assert "none" in criteria and set(criteria) - {"none"} == {e["id"] for e in state["elements"]}
        return ChoiceResult("jev-test", self.choice_id, self.conf, {self.choice_id: self.conf}, 5)


def brief_with(jev, tmp_path, **kw):
    b = Brief(GOAL, trace=str(tmp_path / "t.jsonl"), jev=jev, **kw)
    b.load([F("a"), F("b", "View cart"), F("h", visible=False)], url="file://shop")
    return b


def test_applied_then_reused_when_state_unchanged(tmp_path):
    jev = FakeJev()
    b = brief_with(jev, tmp_path)
    d1 = b.next_click()
    assert d1.outcome == "applied" and d1.fact.id == "a"
    d2 = b.next_click()
    assert d2.outcome == "reused" and d2.fact.id == "a" and jev.calls == 1
    assert d2.record.fingerprint == {"hash": d1.record.fingerprint["hash"], "changed": False, "reused_tick": 1}
    b.load([F("a"), F("c", "Checkout")], url="file://shop")
    assert b.next_click().outcome == "applied" and jev.calls == 2


def test_low_confidence_and_none_take_no_action(tmp_path):
    assert brief_with(FakeJev(confidence=0.3), tmp_path).next_click().fact is None
    d = brief_with(FakeJev(choice="none"), tmp_path).next_click()
    assert d.outcome == "low_confidence" and d.fact is None


def test_error_is_recorded(tmp_path):
    d = brief_with(FakeJev(fail=True), tmp_path).next_click()
    assert d.outcome == "error" and d.fact is None and "boom" in d.record.jev["error"]


def test_every_dropped_fact_in_trace_has_reason(tmp_path):
    d = brief_with(FakeJev(), tmp_path).next_click()
    assert all(f["reason"] for f in d.record.facts if not f["kept"])


def test_load_env_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("JB_A=from_file\nJB_B='quoted'\n# c\nJB_EMPTY=\n")
    monkeypatch.setenv("JB_A", "from_env")
    monkeypatch.delenv("JB_B", raising=False)
    monkeypatch.delenv("JB_EMPTY", raising=False)
    load_env(env)
    import os
    assert os.environ["JB_A"] == "from_env" and os.environ["JB_B"] == "quoted" and "JB_EMPTY" not in os.environ
