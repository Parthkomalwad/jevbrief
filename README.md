<div align="center">

# jevbrief

### Clean, traceable state briefings for TypeSafe's Jev, from any source.

**Other tools show what Jev decided. jevbrief shows what Jev was told, what it wasn't told, and why.**

[![PyPI](https://img.shields.io/pypi/v/jevbrief?color=ff3fd2&label=pypi)](https://pypi.org/project/jevbrief)
[![Python](https://img.shields.io/pypi/pyversions/jevbrief?color=111)](https://pypi.org/project/jevbrief)
[![License: MIT](https://img.shields.io/badge/license-MIT-111)](https://github.com/parthkomalwad/jevbrief/blob/main/LICENSE)
[![Adapters](https://img.shields.io/badge/adapters-web%20%C2%B7%20json%20%C2%B7%20otel-ff3fd2)](#-adapters)
[![Tokens](https://img.shields.io/badge/tokens-up%20to%20%E2%88%9296%25-111)](#-benchmarks)

[Adapters](#-adapters) · [Quick start](#-quick-start) · [Python](#-use-it-in-python) · [Viewer](#-see-every-decision) · [How it works](#-how-it-works) · [Benchmarks](#-benchmarks) · [Build an adapter](#-build-your-own-adapter) · [Contribute](#-contributing)

![Animation: facts from a source flow into the rules, noise is dropped with a reason code, the rest goes to Jev, and Jev picks one](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/pipeline.svg)

</div>

## Why

[Jev](https://docs.typesafe.ai) turns state into typed decisions. It works best on small, relevant state, and it is weak at raw numbers, dates, and long lists of irrelevant detail. Real sources are the opposite: a web page has hundreds of elements, a ticket queue is full of closed and spam tickets, an incident has thousands of log lines.

<table>
<tr>
<td width="33%" valign="top">

**🔌 Adapters**<br>
Read a web page, a JSON file, or OpenTelemetry logs, and turn it into facts, with numbers and dates already turned into plain words.

</td>
<td width="33%" valign="top">

**🧹 Rules with reasons**<br>
Drop the noise with fixed rules. Every dropped fact gets a reason code, so "why didn't it pick the right one?" has an answer.

</td>
<td width="33%" valign="top">

**📉 A token budget**<br>
Keep the state small. Up to **96% fewer input tokens** on our benchmarks, with the same or better accuracy.

</td>
</tr>
<tr>
<td valign="top">

**❓ One clear question**<br>
Question packs ask Jev one narrow judgment and return a typed answer, a confidence, and every option's probability.

</td>
<td valign="top">

**🧾 A trace for every decision**<br>
One JSON line per decision: what was kept, what was dropped and why, and what Jev answered.

</td>
<td valign="top">

**🎬 An animated replay**<br>
`jevbrief view` replays each decision step by step, in one offline HTML file you can attach to a bug report.

</td>
</tr>
</table>

## 🔌 Adapters

![Adapter cards: web pages, JSON data, and OpenTelemetry logs are supported; NES games and Slack and Discord are coming; suggest or build your own](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/adapters.svg)

| Source | Status | Install | Jev answers | Docs |
|---|---|---|---|---|
| **Web pages** (Playwright) | ✅ Supported | `pip install "jevbrief[web]"` | Which element to click next | [web](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/web.md) |
| **JSON and JSON Lines** (any data, with a config file) | ✅ Supported | `pip install jevbrief` | Which item fits, or which action to take | [json](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/json.md) |
| **OpenTelemetry logs** (OTLP JSON) | ✅ Supported | `pip install jevbrief` | Which log group explains an incident | [otel](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/otel.md) |
| **NES games** (Super Mario Bros) | 🔜 v0.3 | `jevbrief[nes]` | Which move to make next | [plan](https://github.com/parthkomalwad/jevbrief/blob/main/docs/roadmap-v0.2.md) |
| **Slack and Discord exports** | 🔜 v0.4 | `jevbrief[chat]` | Which message answers a question | [plan](https://github.com/parthkomalwad/jevbrief/blob/main/docs/roadmap-v0.2.md) |
| **Your source?** | 💡 Open | | | [Suggest it](https://github.com/parthkomalwad/jevbrief/issues/new?template=adapter_request.yml) · [Build it](https://github.com/parthkomalwad/jevbrief/blob/main/ADAPTERS.md) |

## 🚀 Quick start

```bash
pip install "jevbrief[all]"       # everything; or jevbrief (json + otel), or jevbrief[web]
playwright install chromium       # only for web pages
```

`inspect` shows what would be kept and dropped: no API key, no cost. `ask` calls Jev and writes a trace. `--view` opens the animated replay.

<details open>
<summary><b>📜 OpenTelemetry logs: find an incident's cause</b></summary>

```bash
jevbrief ask logs.json --adapter otel --goal "Checkout requests started failing with 500 errors" --view
```

```text
1447 log records -> 23 groups -> 5 sent to Jev
likely cause: auth: failed to load token signing key: certificate expired   (confidence 1.00)
```

</details>

<details>
<summary><b>🗂 JSON data: pick the right record</b></summary>

```bash
jevbrief ask tickets.json --adapter json --config tickets.toml --goal "a customer was billed twice" --view
```

A config maps your data to facts: which list, which fields to send, rules to drop noise, and the question. See the [json docs](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/json.md) and [a full example config](https://github.com/parthkomalwad/jevbrief/blob/main/bench/json/tickets.toml).

</details>

<details>
<summary><b>🌐 Web pages: choose the next click</b></summary>

```bash
jevbrief ask https://news.ycombinator.com --goal "log in" --view
```

</details>

Get an API key at [console.typesafe.ai](https://console.typesafe.ai). Set `TYPESAFE_API_KEY` in your environment, or put `TYPESAFE_API_KEY=...` in a `.env` file where you run the CLI. Run `jevbrief adapters` to see what is installed.

## 🐍 Use it in Python

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

```python
from jevbrief import Brief

brief = Brief(goal="add this item to the cart", trace="traces/agent.jsonl")
await brief.from_page(page)                 # or brief.from_page_sync(page)
decision = brief.next_click()
if decision.fact:
    await page.locator(decision.fact.selector).click()
```

</details>

Every decision comes back the same way:

| `decision.outcome` | Meaning | Your code should |
|---|---|---|
| `applied` | Jev answered at or above `min_confidence` (default 0.5) | Act on `decision.choice` (and `decision.fact` when the options are facts) |
| `reused` | The facts did not change, so the last answer was reused with no API call | Act, but stop if nothing changes |
| `low_confidence` | Below `min_confidence`, or Jev chose "none" | Take no action |
| `error` | The API call failed | Take no action |

Examples: [otel_incident.py](https://github.com/parthkomalwad/jevbrief/blob/main/examples/otel_incident.py) · [json_triage.py](https://github.com/parthkomalwad/jevbrief/blob/main/examples/json_triage.py) · [click_agent.py](https://github.com/parthkomalwad/jevbrief/blob/main/examples/click_agent.py)

## 🎬 See every decision

`jevbrief ask ... --view` opens the viewer after a run, and `jevbrief view` opens the newest trace. Each decision starts with an animated **replay**: every fact read, the dropped ones struck out with their reason, the ones sent to Jev, Jev's answer, and a plain-English "what this means".

![The viewer replaying a JSON decision: facts read, dropped with reasons, sent to Jev, and Jev's answer](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer.png)

Each adapter picks a view of its source:

<table>
<tr>
<td width="50%" valign="top">

**Timeline** (logs): one bar per log group, with the incident start marked.

![Timeline view: the config error is a single mark at the incident start, followed by many symptom errors](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer-timeline.png)

</td>
<td width="50%" valign="top">

**Snapshot** (web pages): the page with Jev's pick boxed in pink.

![Web view: a screenshot of the page with boxes on every element](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer-web.png)

</td>
</tr>
</table>

The viewer is one HTML file with the trace and images embedded. No server, no network.

<details>
<summary><b>🎥 Watch the web adapter drive a browser</b></summary>

![An agent adds an item to the cart and checks out, then the viewer replays what Jev was told](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/demo.gif)

</details>

## ⚙️ How it works

1. **Extract.** The adapter reads the source into facts. Each fact has a `kind`, a `label`, `attrs` that are sent to Jev, and `meta` that is not (positions, raw values). Numbers, counts, and dates become words here.
2. **Rules.** A `RuleSet` scores each fact and drops noise. Core rules are shared; adapters add their own. Remove, add, or reorder rules without forking.
3. **Budget.** Kept facts are sorted by score and cut to a token budget (default 2,000) and an option cap (default 60).
4. **Fingerprint.** If the kept facts did not change, the previous answer is reused and Jev is not called.
5. **Ask Jev.** A question pack builds one or more questions (Choice, Noul, or Score) in a single call. Options can be the facts or a fixed set of actions.
6. **Trace.** One JSON line per decision, with a legend of every reason code used. Images are saved next to the trace.

<details>
<summary><b>Reason codes</b></summary>

Core codes are shared. Adapter codes are namespaced, so adapters never collide.

| Code | Meaning |
|---|---|
| `hidden` | Not observable right now |
| `disabled` | Exists but cannot be acted on |
| `unlabeled` | No usable label, so Jev could not tell what it is |
| `duplicate` | Same kind and label as a higher-scored fact |
| `low_score` | Scored below the keep threshold |
| `budget` | Would have been kept, cut only to fit the token or option budget |
| `<adapter>.<code>` | Adapter rules, for example `web.not_interactive`, `json.closed`, `otel.healthcheck`. Each has a description in the trace |

Force-keep facts with `pins=["<fact id>"]`. Fact IDs are stable across decisions.

</details>

## 📊 Benchmarks

![Benchmark chart: median input tokens, raw vs jevbrief. Web 5,400 vs 2,344. JSON 3,848 vs 2,002. OpenTelemetry logs 29,678 vs 1,070](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/benchmarks.svg)

| Adapter | Tasks | Raw accuracy | jevbrief accuracy | Raw tokens | jevbrief tokens |
|---|---|---|---|---|---|
| web | 10 pages | 100% (30/30) | 100% (30/30) | 5,400 | **2,344** (−57%) |
| json | 9 queries | 89% (24/27) | **100% (27/27)** | 3,848 | **2,002** (−48%) |
| otel | 6 incidents | 83% (15/18) | **100% (18/18)** | 29,678 | **1,070** (−96%) |

Same Jev (`jev-1.13.0`), same question, 3 runs per task, median input tokens. The raw arm sends what a naive integration would send: every element, every record, or the most recent log lines. All data is synthetic and built to look like real sources, and some rules were designed while building these sets, so treat the numbers as illustrations. Details: [web](https://github.com/parthkomalwad/jevbrief/blob/main/bench/results.md) · [json](https://github.com/parthkomalwad/jevbrief/blob/main/bench/json/results.md) · [otel](https://github.com/parthkomalwad/jevbrief/blob/main/bench/otel/results.md). Run them with `jevbrief bench`.

## 🧩 Build your own adapter

An adapter is one class: `extract`, `rules`, `packs`, and optionally `state`. Adding one never changes the core, and removing one never breaks anything.

1. Copy [contrib/adapter_template](https://github.com/parthkomalwad/jevbrief/tree/main/contrib/adapter_template) and its test.
2. Follow [ADAPTERS.md](https://github.com/parthkomalwad/jevbrief/blob/main/ADAPTERS.md): facts, rules, question pack, benchmark.
3. Pass the shared contract test: `check_adapter(MyAdapter(), "sample.json", goal="...")`.
4. Ship it here with a pull request, or as your own package with a `jevbrief.adapters` entry point. jevbrief finds it automatically.

**Using a coding agent?** Copy [skills/jevbrief/SKILL.md](https://github.com/parthkomalwad/jevbrief/blob/main/skills/jevbrief/SKILL.md) into your agent's skills folder (for Claude Code: `.claude/skills/jevbrief/SKILL.md`).

## 🤝 Contributing

| I want to... | Do this |
|---|---|
| 💡 Suggest a source | [Open an adapter request](https://github.com/parthkomalwad/jevbrief/issues/new?template=adapter_request.yml). 👍 the ones you want; the most wanted get built first |
| 🛠 Build an adapter | [Open a proposal](https://github.com/parthkomalwad/jevbrief/issues/new?template=new_adapter.yml), then follow [ADAPTERS.md](https://github.com/parthkomalwad/jevbrief/blob/main/ADAPTERS.md) |
| 🐞 Report a wrong decision | [Open a bug](https://github.com/parthkomalwad/jevbrief/issues/new?template=bug_report.yml) and attach the trace |
| 💬 Ask or share an idea | [Discussions](https://github.com/parthkomalwad/jevbrief/discussions) |

```bash
git clone https://github.com/parthkomalwad/jevbrief && cd jevbrief
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]" && playwright install chromium
pytest -q
```

## 🔒 Privacy

- The API key is read from the environment or `.env` and is never printed, logged, or written to a trace.
- Adapters send only what they list. The web adapter never sends form values; the json adapter sends only `send` fields and buckets; the otel adapter sends message templates with IDs, emails, and addresses replaced.
- Traces contain labels, sources, and (for web pages) a screenshot. Treat them like logs, and use `--no-screenshot` for private pages.

## License

MIT. Community project, not affiliated with TypeSafe AI.
