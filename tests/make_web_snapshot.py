"""Record the web pipeline's output (facts, scores, reasons) on every HTML fixture.

The snapshot in tests/snapshots/web.json was written before the adapter refactor.
tests/test_web_snapshot.py checks that the refactored code produces identical output.
Only regenerate it on purpose, when a change to the web rules is intended:

    python tests/make_web_snapshot.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "tests" / "snapshots" / "web.json"

# (page, goal, budget_tokens). A small budget exercises the `budget` reason code.
CASES = [(t["fixture"].replace("../", ""), t["goal"], 2000)
         for t in json.loads((ROOT / "bench" / "tasks.json").read_text(encoding="utf-8"))]
CASES += [
    ("fixtures/shop_product.html", "add this item to the cart", 400),
    ("tests/pages/shop.html", "add this item to the cart", 2000),
    ("examples/demo_shop.html", "go to checkout", 2000),
]


def run(brief_factory, extract):
    """brief_factory(goal, budget) -> object with facts; extract(page) -> list of facts."""
    from playwright.sync_api import sync_playwright

    out = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        for path, goal, budget in CASES:
            page.goto((ROOT / path).resolve().as_uri(), wait_until="load")
            facts = brief_factory(page, goal, budget)
            out.append({"page": path, "goal": goal, "budget": budget, "facts": [
                [f.id, f.kind, f.label, f.score, f.kept, f.reason] for f in facts]})
        browser.close()
    return out


def current(page, goal, budget):
    sys.path.insert(0, str(ROOT))
    from jevbrief import Brief

    brief = Brief(goal, budget_tokens=budget, trace=None, screenshot=False)
    brief.from_page_sync(page)
    return brief.facts


if __name__ == "__main__":
    SNAPSHOT.parent.mkdir(exist_ok=True)
    data = run(current, None)
    SNAPSHOT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {SNAPSHOT} ({len(data)} cases, {sum(len(c['facts']) for c in data)} facts)")
