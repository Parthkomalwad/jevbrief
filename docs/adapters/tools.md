# tools adapter

Chooses which tool an agent should call next. Works with your own functions, MCP servers, LangChain and LangGraph, CrewAI, and OpenAI or Anthropic tool definitions, mixed in one list.

| | |
|---|---|
| **Reads** | Any list of tools: functions, tool objects, tool dicts, or MCP `tools/list` results |
| **Jev answers** | Which tool to call next, or that no tool fits |
| **Install** | `pip install jevbrief`. No extra dependencies, and no framework is imported. |
| **Main API** | `select_tools()` (ranking only, local and free) and `pick_tool()` (also asks Jev) |
| **Benchmark** | 105 real MCP tools, 40 hand-written goals: 94% with hybrid ranking (88% with keywords) against 82%, with 72% fewer tokens |

## Quick start

```python
from jevbrief import select_tools, pick_tool

def refund_order(order_id: str, amount: float = 0.0):
    """Refund part or all of a customer's order."""

tools = [refund_order, lookup_customer, *mcp_tools, *langchain_tools]      # any mix

relevant = select_tools(tools, "refund order 812", top_k=20)    # your own objects, most relevant first
pick = pick_tool(tools, "refund order 812")                     # pick.tool, pick.tools, pick.confidence
```

`select_tools` never calls Jev and needs no API key. It takes about 10 ms for 100 tools and 90 ms for 1,000.

`pick_tool` asks Jev and writes a trace to `traces/tools.jsonl`, which you can replay with `jevbrief view`. `pick.tool` is `None` when Jev is unsure or no tool fits, and then `pick.tools`, the narrowed list, is the fallback.

From the command line, with a folder of MCP `tools/list` JSON files:

```bash
jevbrief inspect bench/mcp/tools --adapter tools --goal "What time is it in Tokyo right now?"
jevbrief ask     bench/mcp/tools --adapter tools --goal "What time is it in Tokyo right now?" --view
```

## Use with your framework

In every case, the goal should be **the current step**: the latest user message, or your planner's current sub-goal. Don't pass the whole task. "Fix the bug in issue 12" needs `issue_read` first and `create_pull_request` last.

**LangGraph and LangChain.** Narrow the tools in a node before the model:

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from jevbrief import select_tools

tools = await MultiServerMCPClient(servers).get_tools()         # plus any @tool functions of your own

def agent(state):
    goal = state["messages"][-1].content
    return {"messages": [llm.bind_tools(select_tools(tools, goal)).invoke(state["messages"])]}
```

To let Jev choose, and force the model to call that one tool:

```python
pick = pick_tool(tools, goal)                   # in an async node: pick = await apick_tool(tools, goal)
model = llm.bind_tools([pick.tool], tool_choice=pick.tool.name) if pick.tool else llm.bind_tools(pick.tools)
```

**CrewAI.** Give each agent only the tools its task needs:

```python
from crewai_tools import MCPServerAdapter
from jevbrief import select_tools

with MCPServerAdapter(server_params) as mcp_tools:
    tools = [*mcp_tools, *my_crewai_tools]
    analyst = Agent(role="Support analyst", goal="...", tools=select_tools(tools, task.description, top_k=10))
```

**OpenAI and Anthropic SDKs.** Your tool dicts go in, and the same dicts come out:

```python
client.chat.completions.create(model=..., messages=messages, tools=select_tools(openai_tools, user_message))
client.messages.create(model=..., messages=messages, tools=select_tools(anthropic_tools, user_message))
```

**The MCP Python SDK:**

```python
result = await session.list_tools()
tools = select_tools(result.tools, goal)                        # mcp.types.Tool objects
```

## Input

Each tool needs a name and a description. Everything else is optional.

| You pass | Name, description, and parameters come from |
|---|---|
| A Python function | `__name__`, the first paragraph of the docstring, and the signature. Parameters without defaults are required. |
| MCP `tools/list` JSON, or MCP SDK `Tool` | `name`, `description`, `inputSchema`, `annotations` |
| LangChain `BaseTool` or `@tool` | `name`, `description`, `args_schema` |
| CrewAI `BaseTool` | `name`, `description`, `args_schema` |
| OpenAI tool dict | `function.name`, `function.description`, `function.parameters` |
| Anthropic tool dict | `name`, `description`, `input_schema` |
| Any dict or object | `name` and `description` |

**Containers** can be:
- a list, mixed freely
- a `tools/list` result or JSON-RPC response
- a folder of JSON files
- servers keyed by name: `{"github": {"tools": [...]}}`

**Server names** come from the container, from a `server` field or attribute, or from `metadata["server"]`. They are used in `allow`, `deny`, and the option text. Tools without one are shown by name alone.

**Read-only and destructive:**
- MCP tools declare it with `readOnlyHint` and `destructiveHint` annotations.
- For your own tools, set a `read_only` or `destructive` key on a dict, or an attribute on the object:

```python
def lookup_customer(email: str):
    """Find a customer by their email address."""
lookup_customer.read_only = True
```

## How ranking works

An agent with a few servers connected sees a hundred or more tools. Sending all of them costs tokens. In the benchmark, it also made Jev worse: with 105 options it drifted toward general read and list tools. Past about 250 tools, sending them all does not fit Jev's option limit at all.

Ranking runs locally, before Jev sees anything:
1. **Score:** every tool is scored against the goal with **BM25**, a standard keyword-relevance score. A tool's text is its name (split into words, so `listPullRequests` becomes list pull request), its description, and its parameter names and descriptions. Words in the name count double.
2. **Keep:** the top `top_k` tools go to Jev (default 20 in `select_tools` and `pick_tool`, 30 in the adapter).
3. **Drop:** the rest, and any tool with no word in common with the goal, are dropped as `tools.not_relevant`, with each tool's rank and score in the trace.

**Hybrid ranking** adds meaning to keywords, so "show me the README" finds `get_file_contents`:

```python
select_tools(tools, goal, rank="hybrid")                  # local model: pip install "jevbrief[embed]"
select_tools(tools, goal, rank="hybrid", embed=my_embed)  # or your own: texts -> vectors (OpenAI, Voyage, ...)
```

| `rank` | How tools are ordered | Right tool kept (36 goals) | Needs |
|---|---|---|---|
| `"bm25"` (default) | Keywords | 33 | Nothing |
| `"embedding"` | Meaning: cosine similarity of embeddings | 32 | A model |
| `"hybrid"` | Both, fused by reciprocal rank | **35** | A model |

The default model is fastembed's `BAAI/bge-small-en-v1.5`. It runs locally with no PyTorch, downloads once (about 67 MB), and embeds a goal in milliseconds. Tool vectors are cached, so an agent calling every step embeds only the goal.

Two small normalizations run first:
- Any URL becomes the word `url`, which matches tools such as `fetch`.
- A short list of generic abbreviations is expanded: PR, repo, dir, config, msg, db.

| Tools | Ranking time | Sent to Jev | Input tokens, jevbrief | Input tokens, all tools |
|---|---|---|---|---|
| 105 | 10 ms | 15 to 30 | ~800 to 3,700 | ~13,000 |
| 525 | 45 ms | 30 | ~1,600 | over Jev's context |
| 1,050 | 90 ms | 30 | ~1,700 | over Jev's context |

The 525 and 1,050 rows reuse the same 105 tools under new server names, so they measure speed and size only.

## What Jev sees

| Attribute | Values |
|---|---|
| `server` | The server the tool comes from, when known |
| `description` | The first sentence of the description, at most 160 characters |
| `needs` | Its required parameters |
| `effect` | `read-only`, `changes data`, or `destructive`, when the tool declares it |

Jev chooses the tool. It never fills in arguments: your model or your code does that.

## Reason codes

| Code | Meaning |
|---|---|
| `tools.denied` | Outside `allow`, or inside `deny` (tool name, `server.tool`, or `server.*`) |
| `tools.writes` | With `read_only`, the tool declares it changes or deletes data |
| `tools.not_relevant` | Ranked below `top_k`, or has no word in common with the goal |
| `tools.relevant` | Kept: among the top tools for the goal |
| `goal_match` | Kept: the tool name shares a word with the goal (+0.35) |
| Core | `unlabeled`, `low_score`, `budget` |

The core `duplicate` rule is off for this adapter. The same name on two servers (`github.search_code`, `gitlab.search_code`) is two different tools.

## Options

`select_tools(tools, goal, top_k=20, allow=None, deny=None, read_only=False, rank="bm25", embed=None)`

`pick_tool(tools, goal, top_k=20, allow=None, deny=None, read_only=False, rank="bm25", embed=None, trace="traces/tools.jsonl", min_confidence=0.5)`. It also accepts any `Briefing` argument, such as `jev`, `model`, or `trace_level`.

With the adapter directly: `ToolsAdapter({"top_k": 30, "allow": [...], "deny": [...], "read_only": True, "rank": "hybrid"})`, or a path to a JSON file of the same options.

## Question pack

`next_tool` is one Choice over the kept tools, plus "No tool fits; the agent should answer directly or ask the user". It asks which tool to call next to make progress on the goal. In the benchmark, jevbrief chose "none" correctly in all 12 runs of the no-tool tasks. Sending every tool got 8 of 12: it picked `fetch` in all three runs of "book a restaurant".

## Benchmark

[bench/mcp/results.md](../../bench/mcp/results.md) uses:
- 105 real tools from four MCP servers: GitHub's official server, and the time, fetch, and git servers
- 40 hand-written goals, with 3 runs each

| Arm | Accuracy | Median input tokens |
|---|---|---|
| raw (every tool, full description) | 82% | 13,450 |
| jevbrief, keyword ranking (default) | 88% | 3,685 (−73%) |
| jevbrief, hybrid ranking | **94%** | 3,727 (−72%) |

Recollect the tool lists with `python bench/mcp/fetch_tools.py`. It runs each server over stdio. Docker servers need Docker, and `GITHUB_MCP_BIN` runs GitHub's server from its release binary.

## Limits

- **Synonyms:** keyword ranking misses them. In the benchmark it dropped the right tool for "show me the README" (file contents) and "the newest published version" (release). Use `rank="hybrid"`, which fixed both.
- **Goals full of detail:** "Open a bug report: checkout button does nothing on Safari" still fails in every mode, because the bug's own words ("checkout") point at other tools. When you can, pass the action as the goal ("open a bug report"), not the whole message.
- **Similar tools on many servers:** GitHub `list_issues` and Jira `search_issues` compete. Use `allow` or `deny` per step, or name the product in the goal.
- **One step at a time:** it does not remember earlier calls, so it will not notice an agent calling the same tool again and again.
- **Tested frameworks:**
  - Tested against the real packages: `langchain-core` 1.6 and the MCP Python SDK.
  - Tested with objects in the same shape: CrewAI, and the OpenAI and Anthropic dicts.
