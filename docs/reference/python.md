# Python API

```python
from jevbrief import Briefing, Decision, select_tools, pick_tool, apick_tool, check_progress, acheck_progress, loop_signals, Brief
```

## `Briefing`

The pipeline for any adapter: extract, rules, budget, fingerprint, ask Jev, and trace.

```python
from jevbrief import Briefing
from jevbrief.adapters.ci import CiAdapter

brief = Briefing(CiAdapter(), goal="CI is red on main", trace="traces/ci.jsonl")
brief.extract("run.log")          # any source the adapter reads
decision = brief.decide()
```

| Argument | Default | Meaning |
|---|---|---|
| `adapter` | | An adapter instance, or `jevbrief.get_adapter("name")` |
| `goal` | | What the agent is trying to do |
| `pack` | the adapter's first | The question pack name, or a `QuestionPack` |
| `rules` | the adapter's | A `RuleSet`, to add, remove, or reorder rules |
| `budget_tokens` | 2000 | Token budget for the state |
| `max_options` | 60 | Most options in one Choice |
| `trace` | `"trace.jsonl"` | Trace file, or `None` |
| `trace_level` | `"summary"` | `off`, `summary`, or `full` |
| `min_confidence` | 0.5 | Below this, `outcome` is `low_confidence` |
| `pins` | `()` | Fact IDs that are always kept |
| `model` | `"jev-1.13.0"` | The Jev model |
| `jev` | `Jev(model)` | The Jev client: a `Jev` with your own settings, or any object with `model` and `ask` (such as `testing.FakeJev`) |

**Properties and methods:**
- `extract(source)`: extract, filter, and budget in one call.
- `load(facts)`: filter and budget facts you already have.
- `kept`: the facts that will be sent.
- `facts`: every fact, with `reason` and `score`.
- `state()`: exactly what Jev receives.

Calling `decide()` again with unchanged facts reuses the last answer, with no API call.

**Async:** `await brief.adecide()` gives the same result as `decide()` without blocking the event loop. It uses the client's `aask` when it has one (`Jev` does), and otherwise runs `ask` in a worker thread.

**Errors:** a Jev or network failure (the SDK's `TypeSafeError`, which includes a missing API key, rate limits, and timeouts, or an `OSError`) gives `outcome="error"`, and the message is in `decision.record.jev["error"]`. Any other exception is a bug, in an adapter, a rule, or your own code, and is raised.

## `Jev`

The TypeSafe client for one model. Pass it as `Briefing(..., jev=Jev(...))`, or to `pick_tool` and `check_progress`.

```python
from jevbrief.jev import Jev

jev = Jev("jev-1.13.0", timeout=10, retries=3)   # seconds per request; retries with backoff
brief = Briefing(CiAdapter(), goal, jev=jev)
```

| Argument | Default | Meaning |
|---|---|---|
| `model` | `"jev-1.13.0"` | The Jev model |
| `timeout` | the SDK's | Seconds per request |
| `retries` | the SDK's (2) | Retries for connection errors, timeouts, rate limits, and server errors |
| `client`, `async_client` | created on first use | Your own `TypeSafeClient` or `AsyncTypeSafeClient`, for example with a shared HTTP client |

Close long-lived clients with `jev.close()` and `await jev.aclose()`.

## `Decision`

| Field | Meaning |
|---|---|
| `outcome` | `applied`, `reused`, `low_confidence`, or `error` |
| `fact` | The chosen fact, when the options are facts and the outcome is applied or reused |
| `choice` | The chosen option: a fact ID, an action name, or `"none"` |
| `confidence` | Jev's confidence in the choice |
| `answers` | Every answer in the call, including extra questions such as ci's `flaky` |
| `record` | The trace record |

Act on `applied` and `reused`. Take no action on `low_confidence` and `error`.

## `select_tools` and `pick_tool`

Choose which tool an agent should call next, from any mix of functions, MCP tools, LangChain, CrewAI, OpenAI, or Anthropic tools. Both return your own objects. See the [tools adapter](../adapters/tools.md).

```python
select_tools(tools, goal, *, top_k=20, allow=None, deny=None, read_only=False, rank="bm25", embed=None) -> list
pick_tool(tools, goal, *, top_k=20, allow=None, deny=None, read_only=False, rank="bm25", embed=None,
          trace="traces/tools.jsonl", min_confidence=0.5, **briefing) -> Pick   # .tool, .tools, .confidence, .decision
```

`apick_tool(...)` takes the same arguments and is awaited, for async agents.

`select_tools` ranks locally, with no Jev call. `rank="hybrid"` adds embedding similarity to keywords (`pip install "jevbrief[embed]"`, or pass your own `embed` function). `pick_tool` also asks Jev, and `pick.tool` is `None` when Jev is unsure or no tool fits.

## `check_progress` and `loop_signals`

Notice when an agent is stuck, from any step history: step dicts, OpenAI, Anthropic, or LangChain messages, or a jevbrief trace. See the [steps adapter](../adapters/steps.md).

```python
loop_signals(history, window=20) -> list[str]                   # counted loop patterns, no Jev call
check_progress(history, goal, *, window=20, recent=6, trace="traces/progress.jsonl",
               min_confidence=0.5, **briefing) -> Progress     # .stuck, .verdict, .advice, .probability, .signals
```

`acheck_progress(...)` takes the same arguments and is awaited, for async agents.

## `Brief` (web)

A shortcut for Playwright agents.

```python
from jevbrief import Brief

brief = Brief(goal="add this item to the cart", trace="traces/agent.jsonl")
await brief.from_page(page)            # or brief.from_page_sync(page)
decision = await brief.anext_click()   # or brief.next_click()
if decision.fact:
    await page.locator(decision.fact.selector).click()
```

## Customizing rules

Every adapter's rules are a `RuleSet` you can change without forking:

```python
from jevbrief import Boost, Drop, Rule

rules = CiAdapter().rules()
rules = rules.without("ci.passed_step")                                          # remove one
rules = rules.with_rule(Rule("my.no_lint", lambda f, ctx: Drop("my.no_lint")      # add one
                             if "lint" in f.label.lower() else None, "Lint output"), before="goal_match")
brief = Briefing(CiAdapter(), goal, rules=rules)
```

A rule returns `Drop(reason)`, `Boost(delta, name)`, or `None`. Every reason code needs a description. Name your own codes `<namespace>.<code>`.

## Adapters and testing

- `jevbrief.get_adapter("tools")` loads an adapter by name.
- `jevbrief.testing.check_adapter(adapter, source, goal=...)` runs the contract test every adapter must pass.
- `jevbrief.testing.FakeJev` answers with no network, for your own tests.

See [ADAPTERS.md](../../ADAPTERS.md) to build one.
