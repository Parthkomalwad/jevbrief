---
name: jevbrief
description: Add jevbrief to a project so a browser agent asks TypeSafe's Jev which element to click next, with a filtered page state and a trace of what was kept and dropped. Use when building or debugging a Playwright agent, when an agent sends too much page state to a model, or when someone asks why an agent clicked the wrong thing.
---

# Use jevbrief in a project

jevbrief turns a Playwright page into a small list of clickable elements, drops the noise with fixed rules (each drop gets a reason code), asks Jev one question ("which element should be clicked next for this goal?"), and writes a JSONL trace. A local HTML viewer shows the page, Jev's pick, and everything that was dropped.

Use it when an agent needs to pick the next element on a web page. Do not use it for reading page content, filling long forms, or anything other than choosing one element to act on.

## 1. Install

```bash
pip install jevbrief
playwright install chromium
```

Set `TYPESAFE_API_KEY` in the environment, or put `TYPESAFE_API_KEY=...` in a `.env` file where the CLI runs. Never print, log, or commit the key. Make sure `.env` and `traces/` are in `.gitignore`.

## 2. Try it before writing code

```bash
jevbrief inspect <url-or-file> --goal "<goal>"        # no API key, no cost: shows kept and dropped elements
jevbrief ask <url-or-file> --goal "<goal>" --view     # one real decision, then opens the viewer
```

Run `inspect` first. If the correct element is dropped, fix that (see step 5) before calling Jev.

## 3. Pick the integration pattern

**A. Drop-in agent loop (async Playwright)**

```python
from jevbrief import Brief

brief = Brief(goal="add this item to the cart", trace="traces/agent.jsonl")
await brief.from_page(page)
decision = brief.next_click()
if decision.fact:
    await page.locator(decision.fact.selector).click()
else:
    ...  # decision.outcome is "low_confidence" or "error": take no action, ask a human, or stop
```

**B. Sync Playwright**

```python
brief = Brief(goal="log in to my account", trace="traces/agent.jsonl")
brief.from_page_sync(page)
decision = brief.next_click()
if decision.fact:
    page.locator(decision.fact.selector).click()
```

**C. Filter only, bring your own model call**

Use jevbrief as a noise filter and send the result anywhere.

```python
brief = Brief(goal="go to checkout", trace=None)
await brief.from_page(page)
state = brief.state()          # {"goal", "url", "elements": [{"id", "kind", "label", ...}]}
dropped = [(f.label, f.reason) for f in brief.facts if not f.kept]
```

**D. Multi-step goals**

Create one `Brief` per goal and call `from_page` again after every click, because the page changes. If you call `next_click()` twice on an unchanged page, the second call reuses the first answer (`outcome == "reused"`) and makes no API call.

## 4. Handle the outcome

| `decision.outcome` | Meaning | What the agent should do |
|---|---|---|
| `applied` | Jev picked an element with confidence at or above `min_confidence` (default 0.5) | Act on `decision.fact` |
| `reused` | The kept state did not change, so the last answer was reused | Act on `decision.fact`; if the click had no effect, stop to avoid a loop |
| `low_confidence` | Below `min_confidence`, or Jev chose "none of these" | Do not act. Retry with a clearer goal, ask a human, or stop |
| `error` | The API call failed; details in `decision.record.jev["error"]` | Do not act. The SDK already retries rate limits |

Raise `min_confidence` for risky actions (payments, deletes). Tune thresholds on your own pages.

## 5. Debug a wrong click

1. Open the trace: `jevbrief view` (newest trace) or `jevbrief view path/to/trace.jsonl`.
2. In "What Jev saw", check whether the correct element was sent to Jev (blue) or dropped (grey, turn on "dropped").
3. If it was dropped, the reason code tells you why:
   - `budget`: raise `budget_tokens` (default 2000, max 30000) or `max_options` (default 60).
   - `low_score`: the element is far down the page and shares no words with the goal. Reword the goal or pin it.
   - `hidden`, `disabled`: the page state is not ready. Wait or scroll before briefing.
   - `unlabeled`: the element has no text or aria-label. Pin it by ID or fix the page's accessibility.
   - `duplicate`: another element with the same kind and label was kept instead.
4. To force-keep elements: `Brief(goal, pins=["e3fa21"])`. IDs are stable across ticks for the same element.
5. If the element was sent but Jev picked another one, look at "How sure Jev was". A split between two options usually means the goal is ambiguous.

## 6. Settings

`Brief(goal, budget_tokens=2000, max_options=60, trace="trace.jsonl", trace_level="summary", min_confidence=0.5, pins=(), model="jev-1.13.0", screenshot=True)`

- `trace_level`: `off`, `summary` (default), or `full` (also stores the exact state sent to Jev).
- `screenshot=False` (CLI: `--no-screenshot`) for pages with private content. Traces otherwise include a screenshot of the visible page.
- Form values are never sent to Jev. Inputs with a value are marked `filled: true`.

## Rules for the agent using this skill

- Check the installed version's API before relying on these examples: `python -c "import jevbrief, inspect; print(inspect.signature(jevbrief.Brief))"`.
- Never add the API key to code, logs, or traces.
- Never click when `decision.fact` is `None`.
- Report results from the trace, not from memory of what the agent intended.
