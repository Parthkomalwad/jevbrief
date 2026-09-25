<div align="center">

# jevbrief

### Clean, traceable state briefings for TypeSafe's Jev, from any source.

Other tools show what Jev decided. jevbrief shows what Jev was told, what it wasn't told, and why.

[![PyPI](https://img.shields.io/pypi/v/jevbrief?color=ff3fd2&label=pypi)](https://pypi.org/project/jevbrief)
[![Python](https://img.shields.io/pypi/pyversions/jevbrief?color=111)](https://pypi.org/project/jevbrief)
[![License: MIT](https://img.shields.io/badge/license-MIT-111)](https://github.com/parthkomalwad/jevbrief/blob/main/LICENSE)
[![Adapters](https://img.shields.io/badge/adapters-6-ff3fd2)](#adapters)

[Quick start](#quick-start) &nbsp;·&nbsp; [Adapters](#adapters) &nbsp;·&nbsp; [Python](#use-it-in-python) &nbsp;·&nbsp; [Viewer](#see-every-decision) &nbsp;·&nbsp; [How it works](#how-it-works) &nbsp;·&nbsp; [Benchmarks](#benchmarks) &nbsp;·&nbsp; [Contributing](#contributing)

<br>

![Animation: facts from a source flow into the rules, noise is dropped with a reason code, the rest goes to Jev, and Jev picks one](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/pipeline.svg)

</div>

<br>

## Why jevbrief

[Jev](https://docs.typesafe.ai) turns state into typed decisions. It does its best work on small, relevant state, and it is weak at raw numbers, dates, and long lists of irrelevant detail. Real sources are the opposite: a web page has hundreds of elements, an agent sees a hundred tools, and a failed build prints thousands of log lines.

jevbrief sits between your source and Jev. It keeps what matters, drops the rest with a reason for every drop, asks Jev one clear question, and records the whole decision so you can replay it.

![Before and after: 1,395 raw log lines at 29,678 tokens become 5 log groups at 1,070 tokens, and Jev picks the config reload failure](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/before-after.svg)

| | |
|---|---|
| **Adapters** | Read a source into facts, with numbers and dates already turned into plain words. |
| **Rules with reasons** | Fixed rules drop the noise. Every dropped fact gets a reason code, so a wrong answer is debuggable. |
| **A token budget** | 48% to 97% fewer input tokens on our benchmarks, with the same or better accuracy on the main question. |
| **One clear question** | Question packs ask Jev a narrow judgment and return a typed answer, a confidence, and every option's probability. |
| **A trace and a replay** | One JSON line per decision, and `jevbrief view` replays it step by step in one offline HTML file. |

## Quick start

```bash
pip install jevbrief                  # json, otel, ci, and mcp; add [web] or [nes], or [all] for everything
```

Get an API key at [console.typesafe.ai](https://console.typesafe.ai), and set `TYPESAFE_API_KEY` in your environment or in a `.env` file where you run the CLI.

Every adapter uses the same two commands. `inspect` shows what would be kept and dropped, with no API key and no cost. `ask` calls Jev, writes a trace, and `--view` opens the replay.

```bash
gh run view <run id> --log-failed > run.log
jevbrief inspect run.log --adapter ci --goal "CI is red on main"
jevbrief ask     run.log --adapter ci --goal "CI is red on main" --view
```

```text
27 log lines -> 7 failures -> 3 sent to Jev
likely cause: Run pytest -q: E KeyError: 'currency_code'   (confidence 0.84)
looks flaky: no (0.07)
```

Run `jevbrief adapters` to list what is installed. Each adapter's page below has its own quick start.

## Adapters

![Adapter overview: web pages, JSON data, OpenTelemetry logs, CI logs, MCP tool lists, and NES games are supported; Slack and Discord are planned; new sources are open for contribution](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/adapters.svg)

| Adapter | Reads | Jev answers | Install |
|---|---|---|---|
| [ci](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/ci.md) | GitHub Actions logs and JUnit XML | Which error broke the build, and whether it looks flaky | `jevbrief` |
| [mcp](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/mcp.md) | MCP tool lists (`tools/list`) | Which tool the agent should call next | `jevbrief` |
| [otel](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/otel.md) | OpenTelemetry logs (OTLP JSON) | Which log group explains an incident | `jevbrief` |
| [json](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/json.md) | JSON and JSON Lines, with a config file | Which item fits, or which action to take | `jevbrief` |
| [web](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/web.md) | Web pages, through Playwright | Which element to click next | `jevbrief[web]` |
| [nes](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/nes.md) | An NES game's memory ([Nova the Squirrel](https://github.com/NovaSquirrel/NovaTheSquirrel)) | Which move to make next | `jevbrief[nes]` |
| chat | Slack and Discord exports | Which message answers a question | Planned for v0.4 |
| Yours | | | [Suggest it](https://github.com/parthkomalwad/jevbrief/issues/new?template=adapter_request.yml) or [build it](#contributing) |

### Watch Jev play a game

![Jev plays level 1-1 of Nova the Squirrel: each frame shows the facts sent to Jev and the move it picked](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/nes-demo.gif)

Every frame is a real Jev decision. The nes adapter reads the game's memory, turns it into a few facts in words (`Wall ahead, low (one block), touching`), and asks Jev for one move. Play it yourself with `python examples/nes_live.py --rom nova.nes --headed`. The [nes page](https://github.com/parthkomalwad/jevbrief/blob/main/docs/adapters/nes.md) covers getting the free game, the options, and adding another game.

## Use it in Python

Every adapter works the same way: create a `Briefing`, extract, decide.

```python
from jevbrief import Briefing
from jevbrief.adapters.ci import CiAdapter

brief = Briefing(CiAdapter(), goal="CI is red on main", trace="traces/ci.jsonl")
brief.extract(["logs.zip", "reports/junit.xml"])
decision = brief.decide()
if decision.fact:
    print("likely cause:", decision.fact.label, decision.fact.attrs)
```

Every decision comes back in the same shape:

| `decision.outcome` | Meaning | Your code should |
|---|---|---|
| `applied` | Jev answered at or above `min_confidence` (default 0.5) | Act on `decision.choice`, and on `decision.fact` when the options are facts |
| `reused` | The facts did not change, so the last answer was reused with no API call | Act, but stop if nothing changes |
| `low_confidence` | Below `min_confidence`, or Jev chose "none" | Take no action |
| `error` | The API call failed | Take no action |

Extra questions in the same call, such as ci's `flaky`, are in `decision.answers`.

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

More in [examples/](https://github.com/parthkomalwad/jevbrief/tree/main/examples): one script per adapter.

## See every decision

`jevbrief ask ... --view` opens the viewer after a run, and `jevbrief view` opens the newest trace. Each decision starts with an animated replay: every fact read, the dropped ones struck out with their reason, the ones sent to Jev, Jev's answer, and a plain-English summary of what it means.

![The viewer replaying a JSON decision: facts read, dropped with reasons, sent to Jev, and Jev's answer](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer.png)

Each adapter picks the view that fits its source:

| View | Used by | Shows |
|---|---|---|
| Table | json, ci, mcp | Every fact with its score and reason |
| Timeline | otel | One bar per log group, with the incident start marked |
| Snapshot | web | The page with Jev's pick outlined |
| Live | nes | Decisions as they are written, next to the running game (`jevbrief view --live`) |

The viewer is a single HTML file with the trace and images embedded. It needs no server and no network, so it can be attached to a bug report.

<details>
<summary><b>Screenshots: timeline, snapshot, and a browser agent</b></summary>
<br>

![Timeline view: the config error is a single mark at the incident start, followed by many symptom errors](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer-timeline.png)

![Web view: a screenshot of the page with boxes on every element](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/viewer-web.png)

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

Core codes are shared by every adapter. Adapter codes are namespaced as `<adapter>.<code>`, such as `ci.after_failure` or `otel.healthcheck`, and listed on each adapter's page.

| Code | Meaning |
|---|---|
| `hidden` | Not observable right now |
| `disabled` | Exists but cannot be acted on |
| `unlabeled` | No usable label, so Jev could not tell what it is |
| `duplicate` | Same kind and label as a higher-scored fact |
| `low_score` | Scored below the keep threshold |
| `budget` | Would have been kept, cut only to fit the token or option budget |

Force-keep facts with `pins=["<fact id>"]`. Fact IDs are stable across decisions.

</details>

## Benchmarks

![Benchmark chart: median input tokens, raw state against jevbrief, for web, JSON, OpenTelemetry logs, CI logs, MCP tools, and an NES game](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/benchmarks.svg)

| Adapter | Data | Tasks | Raw accuracy | jevbrief accuracy | Raw tokens | jevbrief tokens |
|---|---|---|---|---|---|---|
| [ci](https://github.com/parthkomalwad/jevbrief/blob/main/bench/ci/results.md) | **Real** | 16 failed GitHub Actions runs | 88% | **100%** | 30,502 | **988** (−97%) |
| [mcp](https://github.com/parthkomalwad/jevbrief/blob/main/bench/mcp/results.md) | **Real** tools, hand-written tasks | 40 goals over 105 tools | 82% | **88%** | 13,450 | **3,685** (−73%) |
| [otel](https://github.com/parthkomalwad/jevbrief/blob/main/bench/otel/results.md) | Synthetic | 6 incidents | 83% | **100%** | 29,678 | **1,070** (−96%) |
| [json](https://github.com/parthkomalwad/jevbrief/blob/main/bench/json/results.md) | Synthetic | 9 queries | 89% | **100%** | 3,848 | **2,002** (−48%) |
| [web](https://github.com/parthkomalwad/jevbrief/blob/main/bench/results.md) | Synthetic | 10 pages | 100% | 100% | 5,400 | **2,344** (−57%) |
| [nes](https://github.com/parthkomalwad/jevbrief/blob/main/bench/nes/results.md) | Real game | 100 moves on level 1-1 | block 8.6 | **block 56.4** | 2,829 | **713** (−75%) |

- **Same setup for both arms:** the same Jev (`jev-1.13.0`) and the same question, with three runs per task and median input tokens. The raw arm sends what a naive integration would send: every element, every record, or the most recent log lines.
- **ci's flaky question:** here jevbrief scored lower, 67% against 93%. The raw arm answered "flaky" every time, and 13 of the 16 labels are flaky.
- **mcp's ranking:** keyword ranking dropped the right tool for 3 of 36 goals, all synonyms ("bug report" for issue). With every tool sent, Jev drifted to generic read and list tools.
- **Synthetic sets:** some rules were designed while building them, so treat those numbers as illustrations.

Each adapter name links to its full results and caveats. Reproduce them with `jevbrief bench`.

## Contributing

| To | Do this |
|---|---|
| Suggest a source | [Open an adapter request](https://github.com/parthkomalwad/jevbrief/issues/new?template=adapter_request.yml). Upvote the ones you want; the most requested are built first. |
| Build an adapter | Copy [contrib/adapter_template](https://github.com/parthkomalwad/jevbrief/tree/main/contrib/adapter_template), follow [ADAPTERS.md](https://github.com/parthkomalwad/jevbrief/blob/main/ADAPTERS.md), and pass `check_adapter(MyAdapter(), "sample.json", goal="...")`. Ship it here in a pull request, or as your own package with a `jevbrief.adapters` entry point. |
| Report a wrong decision | [Open a bug report](https://github.com/parthkomalwad/jevbrief/issues/new?template=bug_report.yml) and attach the trace. |
| Ask a question or share an idea | Start a [discussion](https://github.com/parthkomalwad/jevbrief/discussions). |

An adapter is one class with `extract`, `rules`, `packs`, and optionally `state`. Adding one never changes the core, and removing one never breaks anything. Working with a coding agent? Copy [skills/jevbrief/SKILL.md](https://github.com/parthkomalwad/jevbrief/blob/main/skills/jevbrief/SKILL.md) into its skills folder (for Claude Code, `.claude/skills/jevbrief/SKILL.md`).

```bash
git clone https://github.com/parthkomalwad/jevbrief && cd jevbrief
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]" && playwright install chromium
pytest -q
```

## Privacy

- **API key:** read from the environment or `.env`, and never printed, logged, or written to a trace.
- **What adapters send:**
  - The web adapter never sends form values.
  - The json adapter sends only the configured fields and buckets.
  - The otel and ci adapters send message templates, with IDs, emails, and addresses replaced.
- **Traces:** they contain labels, source names, and, for web pages, a screenshot. Treat them like logs, and use `--no-screenshot` for private pages.

## License

MIT. Community project, not affiliated with TypeSafe AI.
