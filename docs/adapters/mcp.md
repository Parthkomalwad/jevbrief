# mcp adapter

Chooses which tool an agent should call next, from its MCP tool lists. Standard library only.

It reads:
- the result of MCP `tools/list` (`{"tools": [...]}`, or the full JSON-RPC response)
- a folder of such files, one per server
- several servers keyed by name (`{"servers": {"github": {"tools": [...]}}}`)
- a plain list of tool dicts, which is what a live agent already holds

```bash
jevbrief inspect bench/mcp/tools --adapter mcp --goal "What time is it in Tokyo right now?"
jevbrief ask     bench/mcp/tools --adapter mcp --goal "What time is it in Tokyo right now?" --view
```

```python
from jevbrief import Briefing
from jevbrief.adapters.mcp import McpAdapter

tools = await session.list_tools()          # from the MCP Python SDK, or any list of tool dicts
brief = Briefing(McpAdapter({"top_k": 30}), goal=user_request, trace="traces/agent.jsonl")
brief.extract([t.model_dump() for t in tools.tools])
decision = brief.decide()
if decision.fact:
    print("call:", decision.fact.meta["server"], decision.fact.label)
```

## Why ranking comes first

An agent with a few servers connected sees a hundred or more tools. Sending all of them costs tokens, and in the benchmark it also made Jev worse: with 105 options it drifted toward general read and list tools.

Picking the 30 tools that matter for this goal is a relevance problem, which fixed rules cannot solve, so the adapter ranks first:
1. **Score:** every tool is scored against the goal with **BM25**, a standard keyword-relevance score. Each tool's text is its name (split into words, so `listPullRequests` becomes list pull request), its description, and its parameter names and descriptions.
2. **Keep:** the top `top_k` tools (default 30) go to Jev.
3. **Drop:** the rest are dropped as `mcp.not_relevant`, with each tool's rank and score in the trace.

Two small normalizations run before ranking:
- Any URL in the goal becomes the word `url`, which matches tools such as `fetch`.
- A short list of generic abbreviations is expanded: PR, repo, dir, config, msg, db.

**Known limit:** keyword ranking misses synonyms. In the benchmark it dropped the right tool for "open a bug report" (the tool says issue), "show me the README" (file contents), and "the newest published version" (release). Optional embedding ranking is planned.

## What Jev sees

| Attribute | Values |
|---|---|
| `server` | The server the tool comes from |
| `description` | The first sentence of the tool's description, at most 160 characters |
| `needs` | Its required parameters |
| `effect` | `read-only`, `changes data`, or `destructive`, from the tool's MCP annotations. Left out when the server does not declare it. |

## Rules

| Rule | Effect |
|---|---|
| `mcp.denied` | Drops tools outside `allow` or inside `deny` (tool names, `server.tool`, or `server.*`) |
| `mcp.writes` | With `read_only`, drops tools whose annotations say they change or delete data |
| `goal_match` | +0.35 when the tool name shares a word with the goal |
| `mcp.not_relevant`, `mcp.relevant` | The ranking: keeps the top `top_k` with a score boost by rank, and drops the rest and any tool with no word in common with the goal |
| Core | `unlabeled`, `duplicate`, `low_score`, `budget` |

## Options

Pass a dict to `McpAdapter({...})`:

```python
McpAdapter({"top_k": 20, "read_only": True, "deny": ["github.delete_file", "slack.*"]})
```

## Question pack

`next_tool` is one Choice over the kept tools, plus "No tool fits; the agent should answer directly or ask the user". It asks which tool to call next to make progress on the goal. In the benchmark, jevbrief answered "none" correctly in all 12 runs of the no-tool tasks. The raw arm answered correctly in 8 of 12: it picked `fetch` in all three runs of "book a restaurant", and a tool in one run of "what is the capital of Australia".

## Benchmark

[bench/mcp/results.md](../../bench/mcp/results.md): 105 real tools from four MCP servers (GitHub's official server, and the time, fetch, and git servers) and 40 hand-written tasks, 3 runs each.

| Arm | Accuracy | Median input tokens |
|---|---|---|
| raw (every tool, full description) | 82% | 13,450 |
| jevbrief (top 30) | 88% | 3,685 (−73%) |

Recollect the tool lists with `python bench/mcp/fetch_tools.py`. It runs each server over stdio. Docker servers need Docker, and `GITHUB_MCP_BIN` runs GitHub's server from its release binary.
