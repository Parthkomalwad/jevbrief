# web adapter

Turns a web page into facts with Playwright: links, buttons, inputs, selects, and headings, with their labels, visibility, and position. Install with `pip install "jevbrief[web]"` and `playwright install chromium`.

| | |
|---|---|
| **Reads** | A live web page, through Playwright |
| **Jev answers** | Which element to click next |
| **Install** | `pip install "jevbrief[web]"`, then `playwright install chromium` |
| **Main API** | `Brief(goal)` with `from_page(page)` and `next_click()`, and `jevbrief ask <url>` |
| **Benchmark** | 10 synthetic pages: both 100%, with 57% fewer tokens |

## Quick start

```bash
jevbrief inspect https://news.ycombinator.com --goal "log in"
jevbrief ask https://news.ycombinator.com --goal "log in" --view
```

## Python

```python
from jevbrief import Brief            # the web shortcut

brief = Brief(goal="add this item to the cart", trace="traces/agent.jsonl")
await brief.from_page(page)            # async Playwright; use from_page_sync(page) for sync
decision = brief.next_click()
if decision.fact:
    await page.locator(decision.fact.selector).click()
```

## What Jev sees

| Field | Value |
|---|---|
| `kind` | `button`, `link`, `input`, `select`, or `text` (headings) |
| `label` | aria-label, linked label, button value, visible text, image alt, placeholder, or title |
| `attrs` (sent) | `type`, `href_path`, `name`, and `filled: true` for inputs with a value (never the value itself) |
| `meta` (not sent) | `selector` (CSS path, used to click), `box`, `y`, `in_viewport` |

Each decision stores a screenshot of the visible page next to the trace, and the viewer draws boxes on it. Turn this off with `--no-screenshot` or `Brief(..., screenshot=False)`.

## Reason codes

In order: `hidden`, `disabled`, `unlabeled`, `web.not_interactive`, `goal_match` (+0.35), `web.in_viewport` (+0.10), `web.far_below` (−0.25 when more than three screens down), `web.near_goal_input` (+0.20 for a button next to a goal-matching input), `duplicate`, then `low_score` below 0.3 and `budget`.

| Code | Meaning |
|---|---|
| `hidden` | Not visible (display none, visibility hidden, aria-hidden, zero size) |
| `disabled` | Element is disabled |
| `unlabeled` | No usable label |
| `web.not_interactive` | A heading with no link to the goal |
| `duplicate` | Same kind and label as a higher-scored element |
| `low_score` | Scored below the keep threshold |
| `budget` | Cut only to fit the token or option budget |

## Question pack

`next_click`: a Choice over the kept elements' IDs, plus "None of these elements helps with the goal".

## Benchmark

[bench/results.md](../../bench/results.md): 10 pages, 3 runs each. Both arms 100% (30/30), with jevbrief at a median of 2,344 input tokens against 5,400 for raw (57% fewer).

## Limits

- **Clicks only.** It chooses the element to click. Typing into inputs and filling forms is your code's job, and input values are never sent to Jev.
- **Shadow DOM and iframes** are not read yet.
- **Synthetic benchmark.** The 10 pages were built for the benchmark.
