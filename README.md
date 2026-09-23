# jevbrief

[![PyPI](https://img.shields.io/pypi/v/jevbrief)](https://pypi.org/project/jevbrief)
[![Python](https://img.shields.io/pypi/pyversions/jevbrief)](https://pypi.org/project/jevbrief)
[![License: MIT](https://img.shields.io/badge/license-MIT-black)](https://github.com/parthkomalwad/jevbrief/blob/main/LICENSE)

> Clean, traceable state briefings for TypeSafe's Jev model.

**Other tools show what Jev decided. jevbrief shows what Jev was told, what it wasn't told, and why.**

jevbrief turns a messy web page into a small, clean briefing for [Jev](https://docs.typesafe.ai), drops the noise with deterministic rules, and records every element it kept or dropped with a reason code. Then it asks Jev one question, "which element should be clicked next for this goal?", and writes a trace you can open in a local viewer.

![The jevbrief trace viewer](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer.png)

<!-- Demo clip: docs/assets/demo.gif (agent clicking through a page, then the viewer) -->

## Benchmark

Same Jev (`jev-1.13.0`), same question, 10 pages, 3 runs each. The raw arm sends every interactive element on the page. The jevbrief arm sends the filtered briefing.

| Arm | Accuracy | Median input tokens | Median latency (ms) | Median confidence | Median options |
|---|---|---|---|---|---|
| raw | 100% (30/30) | 5400 | 408 | 0.98 | 70 |
| **jevbrief** | **100% (30/30)** | **2344** | 392 | 0.99 | **28** |

**57% fewer input tokens and 60% fewer options, with the same accuracy.** Jev is already accurate on these pages, so the gain here is cost and a smaller, auditable state, not accuracy.

These are synthetic pages built to look like real sites (navigation menus, hidden mega menus, cookie banners, product grids, long footers). One salience rule was added after seeing a failure on this set. Full details and caveats are in [bench/results.md](https://github.com/parthkomalwad/jevbrief/blob/main/bench/results.md). Run it yourself with `jevbrief bench`.

## Quick start

```bash
pip install jevbrief
playwright install chromium

# See what jevbrief keeps and drops. No API key needed.
jevbrief inspect https://example.com --goal "find more information"

# Ask Jev for the next click and write a trace (needs TYPESAFE_API_KEY).
jevbrief ask https://example.com --goal "find more information" --view
```

Set `TYPESAFE_API_KEY` in your environment, or put `TYPESAFE_API_KEY=...` in a `.env` file in the folder where you run the CLI. Get a key at [console.typesafe.ai](https://console.typesafe.ai).

## Use it in Python

```python
from jevbrief import Brief

brief = Brief(goal="add this item to the cart", budget_tokens=2000, trace="traces/trace.jsonl")
await brief.from_page(page)              # a Playwright page: extract, filter, budget
decision = brief.next_click()            # fingerprint, ask Jev, write the trace
if decision.fact:
    await page.locator(decision.fact.selector).click()
```

`decision.outcome` is `applied`, `reused` (the page did not change, so the last answer was reused without a call), `low_confidence` (below `min_confidence`, default 0.5, or Jev chose "none of these"), or `error`. In the last two cases `decision.fact` is `None`, so your agent takes no action.

A complete example agent is in [examples/click_agent.py](https://github.com/parthkomalwad/jevbrief/blob/main/examples/click_agent.py). Run `python examples/click_agent.py --headed` to watch it add an item to the cart and check out on a demo page.

## How it works

```text
web page ──► extract ──► salience ──► budget ──► fingerprint ──► Jev ──► trace
            (Playwright)  (drop noise,  (fit tokens   (skip the call   (one Choice  (JSONL, one
                          with reasons)  and options)  if unchanged)    question)    line per decision)
```

1. **Extract.** One browser script collects links, buttons, inputs, selects, and headings, with their labels, visibility, and position.
2. **Salience.** Deterministic rules score each element and drop the noise. Every drop gets a reason code.
3. **Budget.** Kept elements are sorted by score and cut to a token budget (default 2,000) and an option cap (default 60).
4. **Fingerprint.** A hash of the kept state. If it matches the last tick, the previous answer is reused and Jev is not called.
5. **Ask Jev.** One Choice question whose options are the kept element IDs, plus a "none of these" option.
6. **Trace.** One JSON line per decision: what was kept, what was dropped and why, Jev's answer, probabilities, and latency.

### Reason codes

| Code | Meaning |
|---|---|
| `hidden` | Not visible (display none, visibility hidden, aria-hidden, zero size) |
| `disabled` | Element is disabled |
| `not_interactive` | Plain text with no link to the goal |
| `unlabeled` | No usable label, so Jev could not tell what it is |
| `duplicate` | Same kind and label as a higher-scored element |
| `low_score` | Scored below the keep threshold |
| `budget` | Would have been kept, cut only to fit the token or option budget |

Kept elements record the rule that kept them: `goal_match`, `near_goal_input`, `in_viewport`, `base`, or `pinned`. Force-keep elements with `Brief(..., pins=["e14"])`.

## The trace viewer

Add `--view` to `jevbrief ask` to open the viewer as soon as the run finishes, or run `jevbrief view` to open the newest trace in `traces/` (pass a path to open a specific file).

The viewer is a single HTML file with the trace embedded in it. jevbrief writes it to your temp folder and opens it in your browser. There is no server, and it needs no network, so you can also send the file to someone else.

For each decision it shows:

- **What Jev saw:** a screenshot of the page with Jev's pick boxed in pink, elements sent to Jev in blue, and dropped elements (optional) in grey. Hover a box or a table row to match them.
- **Jev picked:** the chosen element, its confidence, and badges for budget cuts, low confidence, or a reused answer.
- **How sure Jev was:** a probability bar for each option.
- **What Jev was told / not told:** every element, with dropped ones grouped by reason code.

![Dropped elements grouped by reason code](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer-dropped.png)

## Privacy

- The API key is read from the environment or `.env` and is never printed, logged, or written to a trace.
- For form fields, jevbrief sends only `filled: true` when a field has a value. It never sends the value itself.
- Traces contain page labels, URLs, and a screenshot of the visible page. Treat them like logs. Use `--no-screenshot` (or `Brief(..., screenshot=False)`) for pages with private content.

## Scope of v0.1

v0.1 is Python only and supports web pages through Playwright. A TypeScript version and other sources are planned, not built.

## Packages

- Python: https://pypi.org/project/jevbrief
- npm: https://www.npmjs.com/package/jevbrief (placeholder, TypeScript version planned)

## License

MIT. Community project, not affiliated with TypeSafe AI.
