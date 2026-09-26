"""The json adapter: any JSON or JSON Lines data, mapped to facts by a config file.

No extra dependencies on Python 3.11+. On 3.10, TOML configs need: pip install "jevbrief[json]".
See docs/adapters/json.md for the config reference.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ...briefing import Extracted
from ...facts import Fact, clean_label, fact_id, register_reasons
from ...questions import FactChoice, OptionChoice, QuestionPack
from ...rules import CORE_RULES, Boost, Drop, GroupRule, Rule, RuleSet
from .. import Adapter, need

MISSING_FIELD = "json.missing_field"
REASONS = {
    MISSING_FIELD: "A field listed in `required` is missing",
    "json.goal_match_fields": "Kept: a `match_fields` value shares a word with the goal",
}
GOAL_MATCH = 0.35
_TEMPLATE = re.compile(r"\{([^{}]+)\}")


def load_config(config) -> dict:
    if isinstance(config, dict):
        return config
    if config is None:
        raise ValueError("the json adapter needs a config: --config mapping.toml (or a dict in Python)")
    path = Path(config)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        need("json", "tomli")
        import tomli as tomllib
    return tomllib.loads(text)


def get(obj, path: str):
    """Read a dotted path such as `customer.tier` or `tags.0`. Returns None when missing."""
    for part in path.split(".") if path else []:
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


def fill(template: str, item) -> str:
    def value(m):
        v = get(item, m.group(1).strip())
        return "" if v is None else ", ".join(map(str, v)) if isinstance(v, list) else str(v)
    return _TEMPLATE.sub(value, template)


def _as_datetime(v) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def check(cond: dict, item, now: datetime) -> bool:
    """Evaluate one condition in code. Numbers and dates are never compared by Jev."""
    v = get(item, cond["field"])
    if "missing" in cond:
        return (v is None) == bool(cond["missing"])
    if v is None:
        return False
    tests = {
        "equals": lambda x: v == x,
        "not_equals": lambda x: v != x,
        "in": lambda x: v in x,
        "not_in": lambda x: v not in x,
        "greater_than": lambda x: isinstance(v, (int, float)) and v > x,
        "less_than": lambda x: isinstance(v, (int, float)) and v < x,
        "matches": lambda x: re.search(x, str(v), re.I) is not None,
        "older_than_days": lambda x: (d := _as_datetime(v)) is not None and (now - d).total_seconds() > x * 86400,
        "newer_than_days": lambda x: (d := _as_datetime(v)) is not None and (now - d).total_seconds() < x * 86400,
    }
    ops = [k for k in cond if k in tests]
    if not ops:
        raise ValueError(f"condition on {cond['field']!r} has no operator. Use one of: {', '.join(tests)}, missing")
    return all(tests[op](cond[op]) for op in ops)


def bucket(spec: dict, item, now: datetime) -> str | None:
    """Turn a number (or a date's age in days, with `age = true`) into a named bucket."""
    v = get(item, spec["field"])
    if spec.get("age"):
        d = _as_datetime(v)
        v = None if d is None else (now - d).total_seconds() / 86400
    if not isinstance(v, (int, float)):
        return None
    for edge, name in zip(spec["edges"], spec["labels"], strict=False):  # one more label than edges
        if v < edge:
            return name
    return spec["labels"][len(spec["edges"])]


class JsonAdapter(Adapter):
    name = "json"
    version = "1"
    renderer = "table"
    extra = "json"
    reasons = REASONS

    def __init__(self, config=None):
        register_reasons(REASONS)
        self.config: dict = {}
        if config is not None:
            self.configure(config)

    def configure(self, config) -> None:
        self.config = load_config(config)
        register_reasons({f"json.{r['name']}": r.get("description", f"Config rule `{r['name']}`")
                          for r in self.config.get("rules", [])}, replace=True)

    def extract(self, source, config=None, **options) -> Extracted:
        if config is not None:
            self.configure(config)
        if not self.config:
            load_config(None)  # raises a clear "needs a config" error
        c = self.config
        data = source
        if isinstance(source, (str, Path)):
            path = Path(source)
            text = path.read_text(encoding="utf-8")
            data = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix == ".jsonl" \
                else json.loads(text)
        items = get(data, c.get("items", "")) if c.get("items") else data
        if not isinstance(items, list):
            raise ValueError(f"`items` = {c.get('items')!r} does not point to a list in the data")
        now = _as_datetime(c["now"]) if c.get("now") else datetime.now(timezone.utc)
        if now is None:
            raise ValueError(f"`now` = {c['now']!r} is not a date. Use an ISO date such as 2026-09-24T00:00:00Z")
        facts = []
        for i, item in enumerate(items):
            attrs = {k: get(item, k) for k in c.get("send", []) if get(item, k) is not None}
            for attr, spec in c.get("buckets", {}).items():
                if (b := bucket(spec, item, now)) is not None:
                    attrs[attr] = b
            fid = fill(c["id"], item) if c.get("id") else fact_id(json.dumps(item, sort_keys=True, default=str))
            facts.append(Fact(
                id=fid, kind=fill(c.get("kind", "item"), item) or "item",
                label=clean_label(fill(c.get("label", ""), item)), attrs=attrs,
                meta={"item": item, "order": i},
            ))
        if len({f.id for f in facts}) != len(facts):
            raise ValueError("the `id` template gives duplicate IDs. Use a field that is unique per item")
        name = Path(source).name if isinstance(source, (str, Path)) else "data"
        return Extracted(facts, {"name": name, "now": now.isoformat()})

    def rules(self) -> RuleSet:
        c = self.config
        _, _, unlabeled, goal_match, duplicate = CORE_RULES
        required = c.get("required", [])
        match_fields = c.get("match_fields", [])

        def now(ctx):
            return _as_datetime(ctx.source.get("now", "")) or datetime.now(timezone.utc)

        rules: list[Rule | GroupRule] = [unlabeled,
                 Rule(MISSING_FIELD, lambda f, ctx: Drop(MISSING_FIELD)
                      if any(get(f.meta["item"], k) is None for k in required) else None)]
        def dropper(code: str, cond) -> Rule:
            return Rule(code, lambda f, ctx: Drop(code) if check(cond, f.meta["item"], now(ctx)) else None)

        def booster(code: str, cond, delta: float) -> Rule:
            return Rule(code, lambda f, ctx: Boost(delta, code) if check(cond, f.meta["item"], now(ctx)) else None)

        for r in c.get("rules", []):
            code = f"json.{r['name']}"
            if "drop_if" in r:
                rules.append(dropper(code, r["drop_if"]))
            if "boost_if" in r:
                rules.append(booster(code, r["boost_if"], r.get("boost", 0.2)))
        rules.append(goal_match)
        if match_fields:
            rules.append(Rule("json.goal_match_fields", lambda f, ctx: Boost(GOAL_MATCH, "json.goal_match_fields")
                              if not ctx.matches(f.label) and any(ctx.matches(fill("{" + k + "}", f.meta["item"]))
                                                                  for k in match_fields) else None))
        rules.append(duplicate)
        return RuleSet(rules, threshold=c.get("keep_threshold", 0.3))

    def packs(self):
        q = self.config.get("question", {})
        instructions = q.get("instructions", "Goal: {goal}\nWhich one item from `items` best fits this goal?")
        extra = q.get("extra", {})
        pack: QuestionPack
        if q.get("options"):
            pack = OptionChoice("choose_option", instructions, q["options"], extra=extra)
        else:
            describe = q.get("describe")
            pack = FactChoice("choose_item", instructions,
                              (lambda f: clean_label(fill(describe, f.meta["item"]))) if describe else None,
                              none_text=q.get("none", "None of these items fits the goal"), extra=extra)
        return {pack.name: pack}

    def state(self, goal, kept, source):
        s = {"goal": goal}
        if self.config.get("context"):
            s["context"] = self.config["context"]
        s["items"] = [f.state() for f in kept]
        return s
