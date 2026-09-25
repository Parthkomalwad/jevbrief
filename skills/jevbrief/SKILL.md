---
name: jevbrief
description: Add jevbrief to a project so an agent asks TypeSafe's Jev a clear question about a filtered state (a web page, JSON data, OpenTelemetry logs, an NES game, and other sources through adapters), with a trace of what was kept, dropped, and why. Use when building an agent that decides from a web page or structured data, when a model is sent too much state, or when someone asks why an agent chose the wrong thing.
---

# Use jevbrief in a project

jevbrief turns a source into small, relevant state for Jev. An **adapter** reads the source into facts, **rules** drop the noise (every drop gets a reason code), a **budget** keeps it small, a **question pack** asks Jev one clear question, and a **trace** records it. `jevbrief view` replays each decision.

| Source | Adapter | Install | Jev answers |
|---|---|---|---|
| Web pages (Playwright) | `web` | `pip install "jevbrief[web]"` then `playwright install chromium` | Which element to click next |
| JSON / JSON Lines with a config | `json` | `pip install jevbrief` | Which item fits, or which fixed action to take |
| OpenTelemetry logs (OTLP JSON), `kubectl get events -o json`, Alertmanager or Prometheus alerts | `otel` | `pip install jevbrief` | Which log group, Kubernetes event, or alert shows an incident's cause |
| CI logs (GitHub Actions) and JUnit XML | `ci` | `pip install jevbrief` | Which error broke the build, and whether it looks flaky |
| Pull request diffs: `gh pr diff`, `.diff`/`.patch`, or `/pulls/{n}/files` JSON | `pr` | `pip install jevbrief` | Which chunk most needs a human reviewer, and whether it is safe to merge |
| Agent step history: dicts, chat messages, LangGraph, or a jevbrief trace | `steps` | `pip install jevbrief` | Is the agent stuck. In code: `loop_signals(history)` or `check_progress(history, goal)` |
| Agent tools: functions, MCP, LangChain, CrewAI, OpenAI, Anthropic | `tools` | `pip install jevbrief` | Which tool the agent should call next. In code: `select_tools(tools, goal)` or `pick_tool(tools, goal)` |
| NES games (Nova the Squirrel; the user supplies the free ROM) | `nes` | `pip install "jevbrief[nes]"` | Which move to make next |

Run `jevbrief adapters` to list what is installed. Other sources need a new adapter (see ADAPTERS.md in the repo).

Set `TYPESAFE_API_KEY` in the environment or in a `.env` file where the CLI runs. Never print, log, or commit it. Put `.env` and `traces/` in `.gitignore`.

## 1. Try it before writing code

`inspect` needs no API key and costs nothing. Run it first and check the right fact is kept.

```bash
jevbrief inspect <url-or-file> --goal "<goal>"                                         # web
jevbrief inspect data.json --adapter json --config map.toml --goal "<goal>"            # json
jevbrief inspect incident/ --adapter otel --goal "<what users see failing>"            # otel: logs, events.json, alerts.json
jevbrief inspect run.log   --adapter ci   --goal "CI is red on main"                     # ci: gh run view --log-failed, a log zip, or JUnit XML
jevbrief inspect pr.diff   --adapter pr   --goal "<the PR's title>"                      # pr: gh pr diff <n> > pr.diff
jevbrief inspect tools/    --adapter tools --goal "<what the user asked the agent>"      # tools: a folder of MCP tools/list JSON
jevbrief ask ... --view                                                                # one real decision + replay
jevbrief view --live traces/nes.jsonl                                                  # watch decisions as they arrive
```

## 2. Integrate

**Any adapter:**

```python
from jevbrief import Briefing, get_adapter

adapter = get_adapter("json")
adapter.configure("map.toml")
brief = Briefing(adapter, goal="a customer was billed twice", trace="traces/app.jsonl")
brief.extract("tickets.json")          # a path, or Python data for json
decision = brief.decide()
if decision.fact:                      # options are facts
    handle(decision.fact.id)
```

**Web shortcut (async or sync Playwright):**

```python
from jevbrief import Brief

brief = Brief(goal="add this item to the cart", trace="traces/agent.jsonl")
await brief.from_page(page)            # or brief.from_page_sync(page)
decision = brief.next_click()
if decision.fact:
    await page.locator(decision.fact.selector).click()
```

**NES game loop:** `python examples/nes_live.py --rom nova.nes --headed`. Never download or link a ROM for the user; point to the free Nova the Squirrel release in `docs/adapters/nes.md`. The emulator is paused while Jev answers, so latency does not affect play.

**Filter only, your own model call:** `brief.extract(...)` then `brief.state()` returns the filtered JSON.

**Multi-step:** extract again after every action, because the source changed. An unchanged state reuses the last answer (`outcome == "reused"`) with no API call.

## 3. Write a json config (when the data is JSON)

```toml
items = "tickets"                    # dotted path to the list
id = "{id}"
label = "{subject}"
kind = "ticket"
send = ["priority", "customer.tier"] # only these fields reach Jev
now = "2026-09-24T12:00:00Z"         # optional fixed time for repeatable runs

[buckets.updated]                    # turn dates and numbers into words in code
field = "updated_at"
age = true
edges = [1, 7]
labels = ["today", "this week", "earlier"]

[[rules]]
name = "closed"                      # reason code json.closed
description = "The ticket is closed"
drop_if = { field = "status", equals = "closed" }

[question]
instructions = "Goal: {goal}\nWhich one ticket in `items` should a support agent open?"
describe = "{subject} ({priority})"
```

Operators: `equals`, `not_equals`, `in`, `not_in`, `greater_than`, `less_than`, `matches`, `older_than_days`, `newer_than_days`, `missing`. Add `[question.options]` for a fixed set of actions instead of choosing an item.

Follow TypeSafe's guidance: compute numbers, dates, and counts in code (buckets); send only fields the question needs; describe options so they are clearly different.

## 4. Handle the outcome

| `decision.outcome` | Meaning | Do |
|---|---|---|
| `applied` | Answer at or above `min_confidence` (default 0.5) | Act on `decision.choice` / `decision.fact` |
| `reused` | Unchanged state, last answer reused | Act; stop if nothing changes, to avoid loops |
| `low_confidence` | Below threshold, or Jev chose "none" | Do not act. Clarify the goal, ask a human, or stop |
| `error` | API failure, in `decision.record.jev["error"]` | Do not act. The SDK already retries rate limits |

Raise `min_confidence` for risky actions (payments, deletes).

## 5. Debug a wrong answer

1. `jevbrief view` (newest trace). Watch the replay, then check "What Jev was not told".
2. If the right fact was dropped, the reason code says why:
   - `budget`: raise `budget_tokens` (default 2000, max 30000) or `max_options` (default 60).
   - `low_score`: it shares no words with the goal and scored low. Reword the goal, or pin it with `pins=["<id>"]`.
   - `hidden`, `disabled`: not observable or not actionable yet. Wait or change the source's state first.
   - `unlabeled`: no label. Fix the source, or the json `label` template.
   - `duplicate`: another fact with the same kind and label was kept.
   - `<adapter>.<code>`: an adapter or config rule. Its description is in the viewer. Remove it with `adapter.rules().without("<code>")` or edit the config.
3. If the right fact was sent but Jev chose another, look at "How sure Jev was". A split usually means the goal or the option descriptions are ambiguous.

## Rules for the agent using this skill

- Check the installed API before relying on these examples: `python -c "import jevbrief, inspect; print(inspect.signature(jevbrief.Briefing))"`.
- Never put the API key in code, logs, or traces.
- Never act when the outcome is `low_confidence` or `error`.
- Report results from the trace, not from what you intended.
