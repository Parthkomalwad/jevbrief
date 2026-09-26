"""The mysource adapter: <one line on what source this reads>.

Copy this folder to jevbrief/adapters/<name>/ and replace every "mysource".
See ADAPTERS.md for the full guide.
"""

from __future__ import annotations

import json
from pathlib import Path

from jevbrief.adapters import Adapter
from jevbrief.briefing import Extracted
from jevbrief.facts import Fact, clean_label, fact_id
from jevbrief.questions import FactChoice
from jevbrief.rules import Drop, Rule, RuleSet, disabled, duplicate, goal_match, hidden, unlabeled

# Every adapter reason code is "<adapter>.<code>", with a plain description.
ARCHIVED = "mysource.archived"
REASONS = {
    ARCHIVED: "The record is archived",
}


class MySourceAdapter(Adapter):
    name = "mysource"
    version = "1"
    renderer = "table"  # "spatial" if you return an image and put meta["box"] on facts
    extra = "mysource"  # the pip extra for optional dependencies, if any
    reasons = REASONS  # registered by the base constructor, which also loads a config (dict, .toml, .json)
    # takes_config = False  # uncomment if this adapter takes no config

    def extract(self, source, **options) -> Extracted:
        # Settings: self.settings(options) is the config with this call's keyword arguments on top.
        # Reading files or folders: jevbrief.sources.find_files(source, (".json",)) handles both.
        # need("mysource", "somepackage")  # uncomment if you use an optional dependency
        records = json.loads(Path(source).read_text(encoding="utf-8"))
        facts = []
        for i, r in enumerate(records):
            facts.append(Fact(
                id=fact_id("mysource", str(r["id"])),
                kind="record",
                label=clean_label(r.get("title")),
                # Sent to Jev: few, semantic values. Compute numbers and dates into words here.
                attrs={"status": r.get("status", "unknown")},
                # Not sent: raw values the rules or viewer need.
                meta={"archived": r.get("archived", False), "order": i},
            ))
        # If the benchmark's raw arm needs more than these facts (for example raw lines), pass raw=[...] too.
        return Extracted(facts, {"name": Path(source).name})

    def rules(self, options: dict | None = None) -> RuleSet:
        # `options` are the keyword arguments of the latest extract(); read settings with self.settings(options).
        archived = Rule(ARCHIVED, lambda f, ctx: Drop(ARCHIVED) if f.meta["archived"] else None)
        return RuleSet([hidden, disabled, unlabeled, archived, goal_match, duplicate])

    def packs(self):
        pack = FactChoice("pick_record", "Goal: {goal}\nWhich one record in `items` best fits this goal?",
                          none_text="No record fits the goal")
        return {pack.name: pack}
