"""A tiny click agent: for each goal, brief the page, ask Jev, and click.

Run:  python examples/click_agent.py
      python examples/click_agent.py https://example.com "your goal" --headed

It stops early when Jev picks "none" or confidence is low.
Needs TYPESAFE_API_KEY in the environment or in a .env file.
"""

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from jevbrief import Brief
from jevbrief.cli import load_env, to_url

HERE = Path(__file__).resolve().parent
DEMO = HERE / "demo_shop.html"


async def run(url: str, goals: list[str], headed: bool, trace: str) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed, slow_mo=400 if headed else 0)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto(to_url(url))
        for goal in goals:
            brief = Brief(goal=goal, trace=trace)
            await brief.from_page(page)
            decision = brief.next_click()
            if not decision.fact:
                print(f"[{goal}] stop: {decision.outcome} ({decision.choice})")
                break
            print(f"[{goal}] click {decision.fact.label!r}  confidence {decision.confidence:.2f}  "
                  f"({len(brief.kept)} of {len(brief.facts)} elements sent)")
            await page.locator(decision.fact.selector).click()
            await page.wait_for_load_state()
        print(f"final page: {page.url.rsplit('/', 1)[-1]}")
        print(f"trace: {trace}  (open it with: jevbrief view {trace})")
        await browser.close()


def main() -> None:
    load_env()
    p = argparse.ArgumentParser(description="Click through a page with jevbrief and Jev.")
    p.add_argument("url", nargs="?", default=str(DEMO), help="Page URL or local HTML file (default: bundled demo shop)")
    p.add_argument("goals", nargs="*", help='One goal per step, e.g. "add this item to the cart" "go to checkout"')
    p.add_argument("--headed", action="store_true", help="Show the browser window")
    p.add_argument("--trace", default="traces/agent.jsonl")
    a = p.parse_args()
    goals = a.goals or ["add this item to the cart", "go to checkout"]
    asyncio.run(run(a.url, goals, a.headed, a.trace))


if __name__ == "__main__":
    main()
