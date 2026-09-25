# Python API

```python
from jevbrief import Briefing, Decision, select_tools, pick_tool, Brief
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

**Properties and methods:**
- `extract(source)`: extract, filter, and budget in one call.
- `load(facts)`: filter and budget facts you already have.
- `kept`: the facts that will be sent.
- `facts`: every fact, with `reason` and `score`.
- `state()`: exactly what Jev receives.

Calling `decide()` again with unchanged facts reuses the last answer, with no API call.

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

`select_tools` ranks locally, with no Jev call. `rank="hybrid"` adds embedding similarity to keywords (`pip install "jevbrief[embed]"`, or pass your own `embed` function). `pick_tool` also asks Jev, and `pick.tool` is `None` when Jev is unsure or no tool fits.

## `Brief` (web)

A shortcut for Playwright agents.

```python
from jevbrief import Brief

brief = Brief(goal="add this item to the cart", trace="traces/agent.jsonl")
await brief.from_page(page)            # or brief.from_page_sync(page)
decision = brief.next_click()
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
