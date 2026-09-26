# jevbrief documentation

jevbrief sits between a source and TypeSafe's Jev. It keeps what matters, drops the rest with a reason for every drop, asks Jev one clear question, and records the decision so you can replay it.

## Quick start

```bash
pip install jevbrief                  # tools, ci, pr, otel, and json; add [web] or [nes], or [all] for everything
```

Get an API key at [console.typesafe.ai](https://console.typesafe.ai), and set `TYPESAFE_API_KEY` in your environment or in a `.env` file.

`inspect` shows what would be kept and dropped, with no API key and no cost. `ask` calls Jev, writes a trace, and `--view` opens the replay:

```bash
jevbrief inspect run.log --adapter ci --goal "CI is red on main"
jevbrief ask     run.log --adapter ci --goal "CI is red on main" --view
```

In Python, every adapter works the same way:

```python
from jevbrief import Briefing
from jevbrief.adapters.ci import CiAdapter

brief = Briefing(CiAdapter(), goal="CI is red on main", trace="traces/ci.jsonl")
brief.extract("run.log")
decision = brief.decide()
```

## Start here

- [How it works](concepts.md): the pipeline, reason codes, outcomes, the viewer, benchmarks, and privacy.
- [Python API](reference/python.md): `Briefing`, `Decision`, `select_tools`, `pick_tool`, and the web `Brief`.
- [Command line](reference/cli.md): `inspect`, `ask`, `view`, `bench`, and `adapters`.

## Adapters

Every adapter page has the same sections: at a glance, quick start, Python, input, what Jev sees, reason codes, options, question pack, benchmark, and limits.

| Adapter | Reads | Jev answers | Install |
|---|---|---|---|
| [tools](adapters/tools.md) | Your functions, MCP servers, LangChain, CrewAI, OpenAI, and Anthropic tools | Which tool the agent should call next | `jevbrief` |
| [steps](adapters/steps.md) | An agent's step history: dicts, chat messages, LangGraph, or a jevbrief trace | Is the agent stuck, making progress, or done | `jevbrief` |
| [ci](adapters/ci.md) | GitHub Actions logs and JUnit XML | Which error broke the build, and whether it looks flaky | `jevbrief` |
| [pr](adapters/pr.md) | A pull request's diff: `gh pr diff`, `.patch`, or the GitHub API | Which chunk most needs a human reviewer, and whether it is safe to merge | `jevbrief` |
| [otel](adapters/otel.md) | OpenTelemetry logs, Kubernetes events, and Prometheus alerts | Which signal shows an incident's cause | `jevbrief` |
| [json](adapters/json.md) | Any JSON or JSON Lines, with a config file | Which item fits, or which action to take | `jevbrief` |
| [web](adapters/web.md) | Web pages, through Playwright | Which element to click next | `jevbrief[web]` |
| [nes](adapters/nes.md) | An NES game's memory | Which move to make next | `jevbrief[nes]` |

## Guides

- [Use jevbrief in an agent framework](adapters/tools.md#use-with-your-framework): LangGraph, CrewAI, and the OpenAI, Anthropic, and MCP SDKs.
- [Build an adapter](../ADAPTERS.md): facts, rules, the question pack, the contract test, and a benchmark.
- [Add another NES game](../skills/jevbrief-nes-game/SKILL.md): from a legal ROM to a tested adapter.
- [Use jevbrief with a coding agent](../skills/jevbrief/SKILL.md): a skill file for Claude Code and similar agents.
- [Stability and changes](stability.md): what is stable, and what changed in each release.

## Benchmarks

The full table and method are in [How it works](concepts.md#benchmarks). Results and caveats per adapter:
- [tools](../bench/mcp/results.md)
- [steps](../bench/steps/results.md)
- [ci](../bench/ci/results.md)
- [pr](../bench/pr/results.md)
- [otel](../bench/otel/results.md), and [with events and alerts](../bench/incident/results.md)
- [json](../bench/json/results.md)
- [web](../bench/results.md)
- [nes](../bench/nes/results.md)
