<div align="center">

# jevbrief

### Clean, traceable state briefings for TypeSafe's Jev, from any source.

Other tools show what Jev decided. jevbrief shows what Jev was told, what it wasn't told, and why.

[![CI](https://github.com/Parthkomalwad/jevbrief/actions/workflows/ci.yml/badge.svg)](https://github.com/Parthkomalwad/jevbrief/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/jevbrief?color=ff3fd2&label=pypi)](https://pypi.org/project/jevbrief)
[![Python](https://img.shields.io/pypi/pyversions/jevbrief?color=111)](https://pypi.org/project/jevbrief)
[![License: MIT](https://img.shields.io/badge/license-MIT-111)](https://github.com/parthkomalwad/jevbrief/blob/main/LICENSE)
[![Docs](https://img.shields.io/badge/docs-read-ff3fd2)](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31)

[**Documentation**](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31) &nbsp;·&nbsp; [Quick start](#quick-start) &nbsp;·&nbsp; [Adapters](#adapters) &nbsp;·&nbsp; [Benchmarks](#benchmarks) &nbsp;·&nbsp; [Contributing](#contributing)

<br>

![Animation: facts from a source flow into the rules, noise is dropped with a reason code, the rest goes to Jev, and Jev picks one](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/pipeline.svg)

</div>

## Why jevbrief

[Jev](https://docs.typesafe.ai) turns state into typed decisions. It does its best work on small, relevant state, and it is weak at raw numbers, dates, and long lists of irrelevant detail. Real sources are the opposite: a web page has hundreds of elements, an agent can call a hundred tools, and a failed build prints thousands of log lines.

jevbrief sits between your source and Jev. It keeps what matters, drops the rest with a reason for every drop, asks Jev one clear question, and records the whole decision so you can replay it.

![Before and after: 1,395 raw log lines at 29,678 tokens become 5 log groups at 1,070 tokens, and Jev picks the config reload failure](https://raw.githubusercontent.com/parthkomalwad/jevbrief/main/docs/assets/before-after.svg)

## Quick start

```bash
pip install jevbrief          # tools, ci, pr, otel, and json; add [web] or [nes], or [all] for everything
```

Set `TYPESAFE_API_KEY` (get one at [console.typesafe.ai](https://console.typesafe.ai)) in your environment or a `.env` file. `inspect` needs no key and costs nothing. `ask` calls Jev and `--view` replays the decision:

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

**Building an agent?** One call narrows any mix of tools to the ones that fit the current step, and returns your own objects. The tools can be your functions, MCP servers, LangChain, CrewAI, OpenAI, or Anthropic tools. Another call tells you when the agent is going in circles.

```python
from jevbrief import select_tools, pick_tool, check_progress

llm.bind_tools(select_tools(tools, goal))     # ranking only: local, free, no API key
pick = pick_tool(tools, goal)                 # Jev picks one: pick.tool, pick.confidence
check_progress(history, goal).stuck          # is the agent going in circles?
```

## Adapters

| Adapter | Reads | Jev answers | Install |
|---|---|---|---|
| [tools](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31#tools) | Your functions, MCP servers, LangChain, CrewAI, OpenAI, and Anthropic tools | Which tool the agent should call next | `jevbrief` |
| [steps](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31#steps) | An agent's step history, from any framework or a jevbrief trace | Is the agent stuck, making progress, or done | `jevbrief` |
| [ci](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31#ci) | GitHub Actions logs and JUnit XML | Which error broke the build, and whether it looks flaky | `jevbrief` |
| [pr](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31#pr) | A pull request's diff: `gh pr diff`, `.patch`, or the GitHub API | Which chunk most needs a human reviewer, and whether it is safe to merge | `jevbrief` |
| [otel](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31#otel) | OpenTelemetry logs, Kubernetes events, and Prometheus alerts | Which signal shows an incident's cause | `jevbrief` |
| [json](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31#json) | Any JSON or JSON Lines, with a config file | Which item fits, or which action to take | `jevbrief` |
| [web](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31#web) | Web pages, through Playwright | Which element to click next | `jevbrief[web]` |
| [nes](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31#nes) | An NES game's memory | Which move to make next | `jevbrief[nes]` |

Each adapter's page covers its quick start, input, reason codes, options, and limits. Want another source? [Suggest it](https://github.com/parthkomalwad/jevbrief/issues/new?template=adapter_request.yml) or [build it](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31#build).

## Benchmarks

Both arms use the same Jev and the same question, with three runs per task and median input tokens. The raw arm sends what a naive integration would send.

| Adapter | Data | Accuracy, raw → jevbrief | Input tokens, raw → jevbrief |
|---|---|---|---|
| tools | 105 real MCP tools, 40 hand-written goals | 82% → **88%** (94% with hybrid ranking) | 13,450 → **3,685** |
| steps | 28 synthetic agent histories | 89% → **93%** | 2,506 → **1,266** |
| ci | 16 real failed GitHub Actions runs | 88% → **100%** | 30,502 → **988** |
| pr | 37 real merged pull requests | 55% → 55% | 2,599 → **1,652** |
| otel | 6 synthetic incidents | 83% → **100%** | 29,678 → **1,070** |
| otel with events and alerts | 8 synthetic incidents | 71% → **100%** | 29,912 → **1,830** |
| json | 9 synthetic queries | 89% → **100%** | 3,848 → **2,002** |
| web | 10 synthetic pages | 100% → 100% | 5,400 → **2,344** |
| nes | 100 moves on a real level | block 8.6 → **block 56.4** | 2,829 → **713** |

Not every result favors jevbrief:
- On ci's second question, whether the failure is flaky, jevbrief scored 67% against 93%.
- On pr, jevbrief tied the full diff on accuracy. It only saved tokens.
- The synthetic sets were built alongside the adapters.

See [how the benchmarks work](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31#concepts.benchmarks) for the method and caveats.

## Contributing

- **Suggest a source:** [open an adapter request](https://github.com/parthkomalwad/jevbrief/issues/new?template=adapter_request.yml).
- **Build an adapter:** follow [the guide](https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31#build).
- **Report a wrong decision:** [open a bug report](https://github.com/parthkomalwad/jevbrief/issues/new?template=bug_report.yml), and attach the trace.

```bash
git clone https://github.com/parthkomalwad/jevbrief && cd jevbrief
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]" && pytest -q && ruff check . && mypy
```

## License

MIT. Community project, not affiliated with TypeSafe AI.
