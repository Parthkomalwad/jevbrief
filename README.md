<div align="center">

# jevbrief

**Clean, traceable state briefings for TypeSafe's Jev model.**

Other tools show what Jev decided. jevbrief shows what Jev was told, what it wasn't told, and why.

[![PyPI](https://img.shields.io/pypi/v/jevbrief?color=ff3fd2)](https://pypi.org/project/jevbrief)
[![Python](https://img.shields.io/pypi/pyversions/jevbrief)](https://pypi.org/project/jevbrief)
[![License: MIT](https://img.shields.io/badge/license-MIT-black)](https://github.com/parthkomalwad/jevbrief/blob/main/LICENSE)

![jevbrief demo: an agent adds an item to the cart and checks out, then the trace viewer shows what Jev was told](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/demo.gif)

</div>

## Why

A browser agent that sends a whole page to a model pays for every nav link, footer link, and hidden menu item. When it clicks the wrong thing, you cannot tell whether the model was wrong or the right button was never sent.

jevbrief sits between your Playwright page and [Jev](https://docs.typesafe.ai):

- **Smaller state.** Fixed rules drop hidden, disabled, unlabeled, duplicate, and off-goal elements. On our benchmark that is **57% fewer input tokens with the same accuracy**.
- **Every drop has a reason.** Each dropped element gets one of seven reason codes, so "why didn't it click Checkout?" has an answer.
- **One question, typed answer.** jevbrief asks Jev one Choice question, "which element should be clicked next for this goal?", and returns the element, the confidence, and the full probability distribution.
- **A trace you can see.** One JSONL line per decision, and a local viewer that shows the page, Jev's pick, and everything that was left out.

## Quick start

```bash
pip install jevbrief
playwright install chromium

# See what jevbrief keeps and drops. No API key, no cost.
jevbrief inspect https://news.ycombinator.com --goal "log in"

# Ask Jev for the next click and open the viewer (needs TYPESAFE_API_KEY).
jevbrief ask https://news.ycombinator.com --goal "log in" --view
```

Get an API key at [console.typesafe.ai](https://console.typesafe.ai). Set `TYPESAFE_API_KEY` in your environment, or put `TYPESAFE_API_KEY=...` in a `.env` file in the folder where you run the CLI.

## Add it to your agent

**Async Playwright**

```python
from jevbrief import Brief

brief = Brief(goal="add this item to the cart", trace="traces/agent.jsonl")
await brief.from_page(page)                 # extract, filter, budget
decision = brief.next_click()               # ask Jev, write the trace
if decision.fact:
    await page.locator(decision.fact.selector).click()
```

**Sync Playwright**

```python
brief = Brief(goal="log in to my account", trace="traces/agent.jsonl")
brief.from_page_sync(page)
decision = brief.next_click()
if decision.fact:
    page.locator(decision.fact.selector).click()
```

**Filter only, with your own model call**

```python
brief = Brief(goal="go to checkout", trace=None)
await brief.from_page(page)
state = brief.state()   # {"goal", "url", "elements": [{"id", "kind", "label", ...}]}
```

**What comes back**

| `decision.outcome` | Meaning | Your agent should |
|---|---|---|
| `applied` | Jev picked an element at or above `min_confidence` (default 0.5) | Click `decision.fact` |
| `reused` | The page did not change, so the last answer was reused with no API call | Click, but stop if nothing happens |
| `low_confidence` | Below `min_confidence`, or Jev chose "none of these" | Take no action |
| `error` | The API call failed | Take no action |

A complete agent is in [examples/click_agent.py](https://github.com/parthkomalwad/jevbrief/blob/main/examples/click_agent.py). Run `python examples/click_agent.py --headed` to watch it add an item to the cart and check out.

### Using a coding agent?

Copy [skills/jevbrief/SKILL.md](https://github.com/parthkomalwad/jevbrief/blob/main/skills/jevbrief/SKILL.md) into your agent's skills folder (for Claude Code: `.claude/skills/jevbrief/SKILL.md`). It teaches the agent how to install jevbrief, pick an integration pattern, handle each outcome, and debug a wrong click from the trace.

## The trace viewer

`jevbrief ask ... --view` opens the viewer after a run. `jevbrief view` opens the newest trace in `traces/`, or you can pass a path.

![The jevbrief trace viewer](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer.png)

- **What Jev saw:** a screenshot of the page. Jev's pick is pink, elements sent to Jev are blue, and dropped elements are grey. Hover a box or a table row to match them.
- **Jev picked:** the chosen element, its confidence, and badges for budget cuts, low confidence, or a reused answer.
- **How sure Jev was:** a probability bar for each option.
- **What Jev was told and not told:** every element, with dropped ones grouped by reason code.

The viewer is one HTML file with the trace embedded. There is no server and it needs no network, so you can attach it to a bug report.

## How it works

![Animation: page elements flow into the salience filter, noise is dropped with a reason code, the rest goes to Jev, and Jev picks "Add to cart"](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/pipeline.svg)

1. **Extract.** One browser script collects links, buttons, inputs, selects, and headings with their labels, visibility, and position.
2. **Salience.** Fixed rules score each element. Goal words in the label, being on screen, and sitting next to a goal-matching field raise the score. Being far down the page lowers it.
3. **Budget.** Kept elements are sorted by score and cut to a token budget (default 2,000) and an option cap (default 60).
4. **Fingerprint.** A hash of the kept state. If it matches the last tick, the previous answer is reused.
5. **Ask Jev.** One Choice question. Options are the kept element IDs plus "none of these".
6. **Trace.** One JSON line per decision.

| Reason code | Meaning |
|---|---|
| `hidden` | Not visible (display none, visibility hidden, aria-hidden, zero size) |
| `disabled` | Element is disabled |
| `not_interactive` | Plain text with no link to the goal |
| `unlabeled` | No usable label, so Jev could not tell what it is |
| `duplicate` | Same kind and label as a higher-scored element |
| `low_score` | Scored below the keep threshold |
| `budget` | Would have been kept, cut only to fit the token or option budget |

Force-keep elements with `Brief(..., pins=["e3fa21"])`. IDs are stable across ticks for the same element.

## Benchmark

Same Jev (`jev-1.13.0`), same question, 10 pages, 3 runs each. The raw arm sends every interactive element. The jevbrief arm sends the filtered briefing.

| Arm | Accuracy | Median input tokens | Median latency (ms) | Median confidence | Median options |
|---|---|---|---|---|---|
| raw | 100% (30/30) | 5400 | 408 | 0.98 | 70 |
| **jevbrief** | **100% (30/30)** | **2344** | 392 | 0.99 | **28** |

Jev is already accurate on these pages, so the gain is cost and a smaller, auditable state, not accuracy. The pages are synthetic but built like real sites (large menus, hidden mega menus, cookie banners, product grids, long footers), and one salience rule was added after seeing a failure on this set. Details are in [bench/results.md](https://github.com/parthkomalwad/jevbrief/blob/main/bench/results.md). Run it yourself with `jevbrief bench`.

## What it supports

| Area | v0.1 (now) | Planned |
|---|---|---|
| Language | Python 3.10+ | TypeScript (`npm install jevbrief`) |
| Sources | Web pages via Playwright (async and sync) | Games, logs, chat, and other state sources |
| Question | "Which element should be clicked next?" (Choice) | More questions, such as "is this task done?" |
| Filtering | 7 reason codes, token and option budget, pins | Custom rules |
| Model | `jev-1.13.0` through the TypeSafe API | New Jev versions as they ship |
| Traces | JSONL at `off` / `summary` / `full`, page screenshot | Comparing traces between runs |
| Viewer | Single offline HTML file | Live view that updates during a run |
| CLI | `inspect`, `ask`, `view`, `bench` | |
| Coding agents | [SKILL.md](https://github.com/parthkomalwad/jevbrief/blob/main/skills/jevbrief/SKILL.md) | |

Want something on the planned list sooner, or something that is not on it? [Open an issue](https://github.com/parthkomalwad/jevbrief/issues).

## Privacy

- The API key is read from the environment or `.env` and is never printed, logged, or written to a trace.
- Form values are never sent. Inputs with a value are marked `filled: true`.
- Traces contain page labels, URLs, and a screenshot of the visible page. Treat them like logs, and use `--no-screenshot` (or `Brief(..., screenshot=False)`) for pages with private content.

## Contributing

```bash
git clone https://github.com/parthkomalwad/jevbrief && cd jevbrief
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]" && playwright install chromium
pytest -q
```

Issues and pull requests are welcome. Please attach the trace file when reporting a wrong click.

## License

MIT. Community project, not affiliated with TypeSafe AI.
