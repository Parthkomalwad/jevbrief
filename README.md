<div align="center">

# jevbrief

**Clean, traceable state briefings for TypeSafe's Jev model, from any source.**

Other tools show what Jev decided. jevbrief shows what Jev was told, what it wasn't told, and why.

[![PyPI](https://img.shields.io/pypi/v/jevbrief?color=ff3fd2)](https://pypi.org/project/jevbrief)
[![Python](https://img.shields.io/pypi/pyversions/jevbrief)](https://pypi.org/project/jevbrief)
[![License: MIT](https://img.shields.io/badge/license-MIT-black)](https://github.com/parthkomalwad/jevbrief/blob/main/LICENSE)
[![Adapters](https://img.shields.io/badge/adapters-web%20%C2%B7%20json-111)](#adapters)

![Animation: facts from a source flow into the rules, noise is dropped with a reason code, the rest goes to Jev, and Jev picks one](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/pipeline.svg)

</div>

## Why

[Jev](https://docs.typesafe.ai) turns state into typed decisions. It works best on small, relevant state, and it is weak at raw numbers, dates, and long lists of irrelevant detail. Real sources are the opposite: a web page has hundreds of elements, a ticket queue has closed and spam tickets, a game has raw RAM values.

jevbrief sits between your source and Jev:

- **Adapters** read a source (a web page, a JSON file, and more coming) and turn it into facts, with numbers and dates already turned into plain words.
- **Rules** drop the noise. Every dropped fact gets a reason code, so "why didn't it pick the right one?" has an answer.
- **A budget** keeps the state within a token limit.
- **Question packs** ask Jev one clear question and return a typed answer with a confidence.
- **Traces and a viewer** record and replay every decision: what Jev was told, what it wasn't, and what it answered.

Measured on our benchmarks: **57% fewer input tokens with the same accuracy on web pages**, and **48% fewer tokens with higher accuracy (100% vs 89%) on JSON data**.

## Adapters

| Source | Status | Install | Jev answers | Docs |
|---|---|---|---|---|
| **Web pages** (Playwright) | ✅ Supported | `pip install "jevbrief[web]"` | Which element to click next | [web](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/web.md) |
| **JSON and JSON Lines** (any data, with a config file) | ✅ Supported | `pip install jevbrief` | Which item fits, or which action to take | [json](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/json.md) |
| **OpenTelemetry logs** | 🔜 Coming in v0.2 | `jevbrief[otel]` | Which error group explains an incident | [plan](https://github.com/parthkomalwad/jevbrief/blob/main/docs/roadmap-v0.2.md) |
| **NES games** (Super Mario Bros) | 🔜 Coming in v0.3 | `jevbrief[nes]` | Which move to make next | [plan](https://github.com/parthkomalwad/jevbrief/blob/main/docs/roadmap-v0.2.md) |
| **Slack and Discord exports** | 🔜 Coming in v0.4 | `jevbrief[chat]` | Which message answers a question | [plan](https://github.com/parthkomalwad/jevbrief/blob/main/docs/roadmap-v0.2.md) |
| **Your source?** | 💡 [Suggest it](https://github.com/parthkomalwad/jevbrief/issues/new?template=adapter_request.yml) or [build it](https://github.com/parthkomalwad/jevbrief/blob/main/ADAPTERS.md) | | | |

Ideas that would make great first adapters: CSV files, RSS feeds, Android screens, terminal screens, Kubernetes events, pull request files, Home Assistant, email. See [ADAPTERS.md](https://github.com/parthkomalwad/jevbrief/blob/main/ADAPTERS.md#good-first-adapters).

## Quick start

```bash
pip install "jevbrief[all]"          # or pick: jevbrief[web], jevbrief (json only)
playwright install chromium          # only for the web adapter
```

`inspect` shows what would be kept and dropped. It needs no API key and costs nothing. `ask` calls Jev and writes a trace. `--view` opens the replay.

**A JSON file** (support tickets, products, records, API responses)

```bash
jevbrief inspect tickets.json --adapter json --config tickets.toml --goal "a customer was billed twice"
jevbrief ask     tickets.json --adapter json --config tickets.toml --goal "a customer was billed twice" --view
```

**A web page**

```bash
jevbrief inspect https://news.ycombinator.com --goal "log in"
jevbrief ask     https://news.ycombinator.com --goal "log in" --view
```

Get an API key at [console.typesafe.ai](https://console.typesafe.ai). Set `TYPESAFE_API_KEY` in your environment, or put `TYPESAFE_API_KEY=...` in a `.env` file where you run the CLI. Run `jevbrief adapters` to list what is installed.

## Use it in Python

Every adapter uses the same three steps: create a `Briefing`, extract, decide.

```python
from jevbrief import Briefing
from jevbrief.adapters.json import JsonAdapter

brief = Briefing(JsonAdapter("tickets.toml"), goal="a customer was billed twice", trace="traces/triage.jsonl")
brief.extract("tickets.json")
decision = brief.decide()
if decision.fact:
    print("open ticket", decision.fact.id)
```

The web adapter has a shortcut for Playwright agents:

```python
from jevbrief import Brief

brief = Brief(goal="add this item to the cart", trace="traces/agent.jsonl")
await brief.from_page(page)                 # or brief.from_page_sync(page)
decision = brief.next_click()
if decision.fact:
    await page.locator(decision.fact.selector).click()
```

Every decision comes back the same way:

| `decision.outcome` | Meaning | Your code should |
|---|---|---|
| `applied` | Jev answered at or above `min_confidence` (default 0.5) | Act on `decision.choice` (and `decision.fact` when the options are facts) |
| `reused` | The facts did not change, so the last answer was reused with no API call | Act, but stop if nothing changes |
| `low_confidence` | Below `min_confidence`, or Jev chose "none" | Take no action |
| `error` | The API call failed | Take no action |

Full examples: [examples/json_triage.py](https://github.com/parthkomalwad/jevbrief/blob/main/examples/json_triage.py) and [examples/click_agent.py](https://github.com/parthkomalwad/jevbrief/blob/main/examples/click_agent.py).

## See every decision

`jevbrief ask ... --view` opens the viewer after a run. `jevbrief view` opens the newest trace.

![The jevbrief viewer replaying a decision: facts read, dropped with reasons, sent to Jev, and Jev's answer](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer.png)

- **Replay:** an animated walk through the decision. Every fact read, the dropped ones struck out with their reason, the ones sent to Jev, and Jev's answer, ending with a plain-English "what this means".
- **What Jev saw:** for sources with an image, such as web pages, a snapshot with Jev's pick boxed in pink.
- **How sure Jev was:** a probability bar for each option.
- **What Jev was told and not told:** every fact, with dropped ones grouped by reason code.

The viewer is one HTML file with the trace and images embedded. There is no server and it needs no network, so you can attach it to a bug report.

<details>
<summary><b>Watch the web adapter drive a browser</b></summary>

![An agent adds an item to the cart and checks out, then the viewer shows what Jev was told](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/demo.gif)

</details>

## How it works

1. **Extract.** The adapter reads the source and returns facts. Each fact has a `kind`, a `label`, `attrs` that are sent to Jev, and `meta` that is not (positions, locators, raw values). Numbers and dates become words here, because Jev is weak at arithmetic and date comparison.
2. **Rules.** A `RuleSet` scores each fact and drops noise. Core rules are shared by every adapter; adapters add their own. You can remove, add, or reorder rules without forking.
3. **Budget.** Kept facts are sorted by score and cut to a token budget (default 2,000) and an option cap (default 60).
4. **Fingerprint.** If the kept facts did not change since the last decision, the previous answer is reused and Jev is not called.
5. **Ask Jev.** A question pack builds one or more questions (Choice, Noul, or Score) in a single call. Options can be the facts themselves or a fixed set of actions.
6. **Trace.** One JSON line per decision, with a legend of every reason code used. Images are saved in a folder next to the trace.

**Reason codes.** Core codes are shared. Adapter codes are namespaced, so adapters never collide.

| Code | Meaning |
|---|---|
| `hidden` | Not observable right now |
| `disabled` | Exists but cannot be acted on |
| `unlabeled` | No usable label, so Jev could not tell what it is |
| `duplicate` | Same kind and label as a higher-scored fact |
| `low_score` | Scored below the keep threshold |
| `budget` | Would have been kept, cut only to fit the token or option budget |
| `<adapter>.<code>` | Adapter rules, for example `web.not_interactive` or `json.closed`. Each has a description in the trace |

Force-keep facts with `pins=["<fact id>"]`. Fact IDs are stable across decisions.

## Benchmarks

Same Jev (`jev-1.13.0`), same question, 3 runs per task. The raw arm sends what a naive integration would send; the jevbrief arm sends the filtered briefing.

| Adapter | Tasks | Raw accuracy | jevbrief accuracy | Raw tokens (median) | jevbrief tokens (median) |
|---|---|---|---|---|---|
| web | 10 pages | 100% (30/30) | 100% (30/30) | 5,400 | **2,344** (−57%) |
| json | 9 queries | 89% (24/27) | **100% (27/27)** | 3,848 | **2,002** (−48%) |

All data is synthetic and built to look like real sources, and some rules were written or tuned while building these sets. Treat the numbers as illustrations, not general results. Details: [web](https://github.com/parthkomalwad/jevbrief/blob/main/bench/results.md), [json](https://github.com/parthkomalwad/jevbrief/blob/main/bench/json/results.md). Run them yourself with `jevbrief bench`.

## Build your own adapter

An adapter is one class with four methods: `extract`, `rules`, `packs`, and optionally `state`. Adding one never changes the core; removing one never breaks anything.

1. Copy [contrib/adapter_template](https://github.com/parthkomalwad/jevbrief/tree/main/contrib/adapter_template) and its test.
2. Follow [ADAPTERS.md](https://github.com/parthkomalwad/jevbrief/blob/main/ADAPTERS.md): facts, rules, question pack, benchmark.
3. Pass the shared contract test: `check_adapter(MyAdapter(), "sample.json", goal="...")`.
4. Ship it inside jevbrief with a pull request, or as your own package: add a `jevbrief.adapters` entry point and jevbrief finds it.

### Using a coding agent?

Copy [skills/jevbrief/SKILL.md](https://github.com/parthkomalwad/jevbrief/blob/main/skills/jevbrief/SKILL.md) into your agent's skills folder (for Claude Code: `.claude/skills/jevbrief/SKILL.md`). It teaches the agent to add jevbrief to a project, pick an adapter, handle each outcome, and debug a wrong answer from the trace.

## Contributing

- 💡 **Suggest a source:** [open an adapter request](https://github.com/parthkomalwad/jevbrief/issues/new?template=adapter_request.yml). Give 👍 to the requests you want; the most wanted get built first.
- 🛠 **Build an adapter:** [open a proposal](https://github.com/parthkomalwad/jevbrief/issues/new?template=new_adapter.yml), then follow [ADAPTERS.md](https://github.com/parthkomalwad/jevbrief/blob/main/ADAPTERS.md).
- 🐞 **Report a wrong decision:** [open a bug](https://github.com/parthkomalwad/jevbrief/issues/new?template=bug_report.yml) and attach the trace.
- 💬 **Ideas and questions:** [Discussions](https://github.com/parthkomalwad/jevbrief/discussions).

```bash
git clone https://github.com/parthkomalwad/jevbrief && cd jevbrief
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]" && playwright install chromium
pytest -q
```

## Privacy

- The API key is read from the environment or `.env` and is never printed, logged, or written to a trace.
- Adapters send only the fields they list. The web adapter never sends form values; the json adapter sends only the `send` fields and buckets.
- Traces contain labels, sources, and (for the web adapter) a screenshot of the visible page. Treat them like logs, and use `--no-screenshot` for private pages.

## License

MIT. Community project, not affiliated with TypeSafe AI.
