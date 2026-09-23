<div align="center">

# jevbrief

### Clean, traceable state briefings for TypeSafe's Jev, from any source.

Other tools show what Jev decided. jevbrief shows what Jev was told, what it wasn't told, and why.

[![PyPI](https://img.shields.io/pypi/v/jevbrief?color=ff3fd2&label=pypi)](https://pypi.org/project/jevbrief)
[![Python](https://img.shields.io/pypi/pyversions/jevbrief?color=111)](https://pypi.org/project/jevbrief)
[![License: MIT](https://img.shields.io/badge/license-MIT-111)](https://github.com/parthkomalwad/jevbrief/blob/main/LICENSE)
[![Adapters](https://img.shields.io/badge/adapters-web%20%C2%B7%20json%20%C2%B7%20otel-ff3fd2)](#adapters)

[Adapters](#adapters) &nbsp;·&nbsp; [Quick start](#quick-start) &nbsp;·&nbsp; [Python](#use-it-in-python) &nbsp;·&nbsp; [Viewer](#see-every-decision) &nbsp;·&nbsp; [How it works](#how-it-works) &nbsp;·&nbsp; [Benchmarks](#benchmarks) &nbsp;·&nbsp; [Build an adapter](#build-your-own-adapter) &nbsp;·&nbsp; [Contributing](#contributing)

<br>

![Animation: facts from a source flow into the rules, noise is dropped with a reason code, the rest goes to Jev, and Jev picks one](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/pipeline.svg)

</div>

<br>

## Why jevbrief

[Jev](https://docs.typesafe.ai) turns state into typed decisions. It does its best work on small, relevant state, and it is weak at raw numbers, dates, and long lists of irrelevant detail. Real sources are the opposite: a web page has hundreds of elements, a ticket queue is full of closed and spam tickets, and an incident produces thousands of log lines.

jevbrief sits between your source and Jev. It keeps what matters, drops the rest with a reason for every drop, asks Jev one clear question, and records the whole decision so you can replay it.

![Before and after: 1,395 raw log lines at 29,678 tokens become 5 log groups at 1,070 tokens, and Jev picks the config reload failure](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/before-after.svg)

<table>
<tr>
<td width="33%" valign="top">

**Adapters**

Read a web page, a JSON file, or OpenTelemetry logs into facts, with numbers and dates already turned into plain words.

</td>
<td width="33%" valign="top">

**Rules with reasons**

Fixed rules drop the noise. Every dropped fact gets a reason code, so a wrong answer is debuggable.

</td>
<td width="33%" valign="top">

**A token budget**

Up to 96% fewer input tokens on our benchmarks, with the same or better accuracy.

</td>
</tr>
<tr>
<td valign="top">

**One clear question**

Question packs ask Jev a narrow judgment and return a typed answer, a confidence, and every option's probability.

</td>
<td valign="top">

**A trace per decision**

One JSON line per decision: what was kept, what was dropped and why, and what Jev answered.

</td>
<td valign="top">

**An animated replay**

`jevbrief view` replays each decision step by step, in one offline HTML file.

</td>
</tr>
</table>

## Adapters

![Adapter overview: web pages, JSON data, and OpenTelemetry logs are supported; NES games and Slack and Discord are planned; new sources are open for contribution](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/adapters.svg)

| Source | Status | Install | Jev answers | Docs |
|---|---|---|---|---|
| Web pages (Playwright) | Supported | `pip install "jevbrief[web]"` | Which element to click next | [web](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/web.md) |
| JSON and JSON Lines, with a config file | Supported | `pip install jevbrief` | Which item fits, or which action to take | [json](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/json.md) |
| OpenTelemetry logs (OTLP JSON) | Supported | `pip install jevbrief` | Which log group explains an incident | [otel](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/otel.md) |
| NES games (Super Mario Bros) | Planned for v0.3 | `jevbrief[nes]` | Which move to make next | [roadmap](https://github.com/parthkomalwad/jevbrief/blob/main/docs/roadmap-v0.2.md) |
| Slack and Discord exports | Planned for v0.4 | `jevbrief[chat]` | Which message answers a question | [roadmap](https://github.com/parthkomalwad/jevbrief/blob/main/docs/roadmap-v0.2.md) |
| Your source | Open | | | [Suggest it](https://github.com/parthkomalwad/jevbrief/issues/new?template=adapter_request.yml) or [build it](https://github.com/parthkomalwad/jevbrief/blob/main/ADAPTERS.md) |

## Quick start

```bash
pip install "jevbrief[all]"       # everything; or jevbrief (json and otel), or jevbrief[web]
playwright install chromium       # only for web pages
```

`inspect` shows what would be kept and dropped, with no API key and no cost. `ask` calls Jev and writes a trace. `--view` opens the animated replay.

<details open>
<summary><b>OpenTelemetry logs: find the cause of an incident</b></summary>
<br>

```bash
jevbrief ask logs.json --adapter otel --goal "Checkout requests started failing with 500 errors" --view
```

```text
1447 log records -> 23 groups -> 5 sent to Jev
likely cause: auth: failed to load token signing key: certificate expired   (confidence 1.00)
```

</details>

<details>
<summary><b>JSON data: pick the right record</b></summary>
<br>

```bash
jevbrief ask tickets.json --adapter json --config tickets.toml --goal "a customer was billed twice" --view
```

A config maps your data to facts: which list to read, which fields to send, which rules drop noise, and what to ask. See the [json docs](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/json.md) and a [complete example config](https://github.com/parthkomalwad/jevbrief/blob/main/bench/json/tickets.toml).

</details>

<details>
<summary><b>Web pages: choose the next click</b></summary>
<br>

```bash
jevbrief ask https://news.ycombinator.com --goal "log in" --view
```

</details>

Get an API key at [console.typesafe.ai](https://console.typesafe.ai). Set `TYPESAFE_API_KEY` in your environment, or put `TYPESAFE_API_KEY=...` in a `.env` file where you run the CLI. Run `jevbrief adapters` to list what is installed.

## Use it in Python

Every adapter works the same way: create a `Briefing`, extract, decide.

```python
from jevbrief import Briefing
from jevbrief.adapters.otel import OtelAdapter

brief = Briefing(OtelAdapter(), goal="Checkout requests started failing with 500 errors", trace="traces/incident.jsonl")
brief.extract("logs.json")
decision = brief.decide()
if decision.fact:
    print("likely cause:", decision.fact.label, decision.fact.attrs)
```

<details>
<summary><b>Web shortcut for Playwright agents</b></summary>
<br>

```python
from jevbrief import Brief

brief = Brief(goal="add this item to the cart", trace="traces/agent.jsonl")
await brief.from_page(page)                 # or brief.from_page_sync(page)
decision = brief.next_click()
if decision.fact:
    await page.locator(decision.fact.selector).click()
```

</details>

Every decision comes back in the same shape:

| `decision.outcome` | Meaning | Your code should |
|---|---|---|
| `applied` | Jev answered at or above `min_confidence` (default 0.5) | Act on `decision.choice`, and on `decision.fact` when the options are facts |
| `reused` | The facts did not change, so the last answer was reused with no API call | Act, but stop if nothing changes |
| `low_confidence` | Below `min_confidence`, or Jev chose "none" | Take no action |
| `error` | The API call failed | Take no action |

Examples: [otel_incident.py](https://github.com/parthkomalwad/jevbrief/blob/main/examples/otel_incident.py) · [json_triage.py](https://github.com/parthkomalwad/jevbrief/blob/main/examples/json_triage.py) · [click_agent.py](https://github.com/parthkomalwad/jevbrief/blob/main/examples/click_agent.py)

## See every decision

`jevbrief ask ... --view` opens the viewer after a run, and `jevbrief view` opens the newest trace. Each decision starts with an animated replay: every fact read, the dropped ones struck out with their reason, the ones sent to Jev, Jev's answer, and a plain-English summary of what it means.

![The viewer replaying a JSON decision: facts read, dropped with reasons, sent to Jev, and Jev's answer](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer.png)

Each adapter chooses the view that fits its source.

<table>
<tr>
<td width="50%" valign="top">

**Timeline**, for logs: one bar per log group, with the incident start marked.

![Timeline view: the config error is a single mark at the incident start, followed by many symptom errors](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer-timeline.png)

</td>
<td width="50%" valign="top">

**Snapshot**, for web pages: the page with Jev's pick outlined.

![Web view: a screenshot of the page with boxes on every element](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer-web.png)

</td>
</tr>
</table>

The viewer is a single HTML file with the trace and images embedded. It needs no server and no network, so it can be attached to a bug report.

<details>
<summary><b>Watch the web adapter drive a browser</b></summary>
<br>

![An agent adds an item to the cart and checks out, then the viewer replays what Jev was told](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/demo.gif)

</details>

## How it works

| Step | What happens |
|---|---|
| **1. Extract** | The adapter reads the source into facts. Each fact has a `kind`, a `label`, `attrs` sent to Jev, and `meta` kept private. Numbers, counts, and dates become words here. |
| **2. Rules** | A `RuleSet` scores each fact and drops noise. Core rules are shared, adapters add their own, and you can remove, add, or reorder rules without forking. |
| **3. Budget** | Kept facts are sorted by score and cut to a token budget (default 2,000) and an option cap (default 60). |
| **4. Fingerprint** | If the kept facts have not changed, the previous answer is reused and Jev is not called. |
| **5. Ask Jev** | A question pack builds one or more questions (Choice, Noul, or Score) in a single call. Options are either the facts or a fixed set of actions. |
| **6. Trace** | One JSON line per decision, with a legend of every reason code used. Images are stored next to the trace. |

<details>
<summary><b>Reason codes</b></summary>
<br>

Core codes are shared by every adapter. Adapter codes are namespaced, so adapters never collide.

| Code | Meaning |
|---|---|
| `hidden` | Not observable right now |
| `disabled` | Exists but cannot be acted on |
| `unlabeled` | No usable label, so Jev could not tell what it is |
| `duplicate` | Same kind and label as a higher-scored fact |
| `low_score` | Scored below the keep threshold |
| `budget` | Would have been kept, cut only to fit the token or option budget |
| `<adapter>.<code>` | Adapter rules such as `web.not_interactive`, `json.closed`, or `otel.healthcheck`, each described in the trace |

Force-keep facts with `pins=["<fact id>"]`. Fact IDs are stable across decisions.

</details>

## Benchmarks

![Benchmark chart: median input tokens, raw state against jevbrief, for web, JSON, and OpenTelemetry logs](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/benchmarks.svg)

| Adapter | Tasks | Raw accuracy | jevbrief accuracy | Raw tokens | jevbrief tokens |
|---|---|---|---|---|---|
| web | 10 pages | 100% (30/30) | 100% (30/30) | 5,400 | **2,344** (−57%) |
| json | 9 queries | 89% (24/27) | **100% (27/27)** | 3,848 | **2,002** (−48%) |
| otel | 6 incidents | 83% (15/18) | **100% (18/18)** | 29,678 | **1,070** (−96%) |

Same Jev (`jev-1.13.0`), same question, three runs per task, median input tokens. The raw arm sends what a naive integration would send: every element, every record, or the most recent log lines. The data is synthetic and built to resemble real sources, and some rules were designed while building these sets, so treat the numbers as illustrations rather than general results. Details: [web](https://github.com/parthkomalwad/jevbrief/blob/main/bench/results.md) · [json](https://github.com/parthkomalwad/jevbrief/blob/main/bench/json/results.md) · [otel](https://github.com/parthkomalwad/jevbrief/blob/main/bench/otel/results.md). Reproduce them with `jevbrief bench`.

## Build your own adapter

An adapter is one class with `extract`, `rules`, `packs`, and optionally `state`. Adding one never changes the core, and removing one never breaks anything.

1. Copy [contrib/adapter_template](https://github.com/parthkomalwad/jevbrief/tree/main/contrib/adapter_template) and its test.
2. Follow [ADAPTERS.md](https://github.com/parthkomalwad/jevbrief/blob/main/ADAPTERS.md) for facts, rules, the question pack, and the benchmark.
3. Pass the shared contract test: `check_adapter(MyAdapter(), "sample.json", goal="...")`.
4. Ship it here in a pull request, or as your own package with a `jevbrief.adapters` entry point, which jevbrief discovers automatically.

Working with a coding agent? Copy [skills/jevbrief/SKILL.md](https://github.com/parthkomalwad/jevbrief/blob/main/skills/jevbrief/SKILL.md) into its skills folder (for Claude Code, `.claude/skills/jevbrief/SKILL.md`).

## Contributing

| To | Do this |
|---|---|
| Suggest a source | [Open an adapter request](https://github.com/parthkomalwad/jevbrief/issues/new?template=adapter_request.yml). Upvote the ones you want; the most requested are built first. |
| Build an adapter | [Open a proposal](https://github.com/parthkomalwad/jevbrief/issues/new?template=new_adapter.yml), then follow [ADAPTERS.md](https://github.com/parthkomalwad/jevbrief/blob/main/ADAPTERS.md). |
| Report a wrong decision | [Open a bug report](https://github.com/parthkomalwad/jevbrief/issues/new?template=bug_report.yml) and attach the trace. |
| Ask a question or share an idea | Start a [discussion](https://github.com/parthkomalwad/jevbrief/discussions). |

```bash
git clone https://github.com/parthkomalwad/jevbrief && cd jevbrief
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]" && playwright install chromium
pytest -q
```

## Privacy

- The API key is read from the environment or `.env` and is never printed, logged, or written to a trace.
- Adapters send only what they list. The web adapter never sends form values, the json adapter sends only the configured fields and buckets, and the otel adapter sends message templates with IDs, emails, and addresses replaced.
- Traces contain labels, source names, and, for web pages, a screenshot. Treat them like logs, and use `--no-screenshot` for private pages.

## License

MIT. Community project, not affiliated with TypeSafe AI.
