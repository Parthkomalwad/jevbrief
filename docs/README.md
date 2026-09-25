# jevbrief documentation

jevbrief sits between a source and TypeSafe's Jev. It keeps what matters, drops the rest with a reason for every drop, asks Jev one clear question, and records the decision so you can replay it.

## Start here

- [Quick start](../README.md#quick-start): install, set your API key, and run a first decision.
- [How it works](../README.md#how-it-works): facts, rules, the budget, the question, and the trace.
- [Python API](reference/python.md): `Briefing`, `Decision`, `select_tools`, `pick_tool`, and the web `Brief`.
- [Command line](reference/cli.md): `inspect`, `ask`, `view`, `bench`, and `adapters`.

## Adapters

Every adapter page has the same sections: at a glance, quick start, Python, input, what Jev sees, reason codes, options, question pack, benchmark, and limits.

| Adapter | Reads | Jev answers | Install |
|---|---|---|---|
| [tools](adapters/tools.md) | Your functions, MCP servers, LangChain, CrewAI, OpenAI, and Anthropic tools | Which tool the agent should call next | `jevbrief` |
| [ci](adapters/ci.md) | GitHub Actions logs and JUnit XML | Which error broke the build, and whether it looks flaky | `jevbrief` |
| [otel](adapters/otel.md) | OpenTelemetry logs (OTLP JSON) | Which log group explains an incident | `jevbrief` |
| [json](adapters/json.md) | Any JSON or JSON Lines, with a config file | Which item fits, or which action to take | `jevbrief` |
| [web](adapters/web.md) | Web pages, through Playwright | Which element to click next | `jevbrief[web]` |
| [nes](adapters/nes.md) | An NES game's memory | Which move to make next | `jevbrief[nes]` |

## Guides

- [Use jevbrief in an agent framework](adapters/tools.md#use-with-your-framework): LangGraph, CrewAI, and the OpenAI, Anthropic, and MCP SDKs.
- [Build an adapter](../ADAPTERS.md): facts, rules, the question pack, the contract test, and a benchmark.
- [Add another NES game](../skills/jevbrief-nes-game/SKILL.md): from a legal ROM to a tested adapter.
- [Use jevbrief with a coding agent](../skills/jevbrief/SKILL.md): a skill file for Claude Code and similar agents.

## Benchmarks

Each adapter is measured the same way. The raw arm sends what a naive integration would send, and the jevbrief arm sends the kept facts. Both use the same Jev and the same question, with three runs per task.

Results and caveats:
- [tools](../bench/mcp/results.md)
- [ci](../bench/ci/results.md)
- [otel](../bench/otel/results.md)
- [json](../bench/json/results.md)
- [web](../bench/results.md)
- [nes](../bench/nes/results.md)
