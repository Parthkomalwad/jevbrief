# steps adapter

Notices when an agent is stuck: repeating the same call, cycling between calls, or failing the same way, without getting closer to its goal. Works on any agent's step history, including your own jevbrief traces.

| | |
|---|---|
| **Reads** | Step dicts, OpenAI or Anthropic chat messages, LangChain and LangGraph messages, or a jevbrief trace |
| **Jev answers** | Is the agent making progress, stuck repeating, stuck failing, or done? Plus a stuck probability and what to do next |
| **Install** | `pip install jevbrief`. Standard library only. |
| **Main API** | `loop_signals()` (counting only, local and free) and `check_progress()` (also asks Jev) |
| **Benchmark** | 28 synthetic agent histories: 93% against 89%, with 49% fewer tokens |

## Quick start

```python
from jevbrief import check_progress, loop_signals

steps = [{"tool": "search_code", "args": {"q": "round_total"}, "result": "0 results"}] * 5

loop_signals(steps)
# ['search_code called 5 times in a row with the same arguments, the same result each time',
#  'new information in 1 of the last 5 steps']

p = check_progress(steps, goal="Find where invoice totals are rounded")
p.stuck, p.verdict, p.advice, p.probability
# True, 'stuck_repeating', 'change_arguments', 0.96
```

`loop_signals` never calls Jev and needs no API key. `check_progress` asks Jev, and writes a trace to `traces/progress.jsonl` that you can replay with `jevbrief view`.

It works on a jevbrief trace too. This is the NES demo, where Nova got stuck at a wall:

```bash
jevbrief inspect traces/nes.jsonl --adapter steps --goal "Get Nova to the end of the level"
```

```text
62 facts found, 8 kept, 54 dropped, ~200 of 2000 tokens

KEPT
  eb4e0b9  0.80  repeat  'jump_right called 20 times in a row with the same arguments, the same result eac' steps.loop
  e30350d  0.60  step    'jump_right'                                  steps.recent
  ...
  e056d7b  0.50  novelty 'new information in 0 of the last 8 steps'    base
```

## Use it in an agent loop

Check every few steps. Only act when the answer is confident:

```python
for i, step in enumerate(agent.run(task)):
    history.append(step)
    if i % 5 == 4:
        p = check_progress(history, goal=current_goal)
        if p.stuck and p.advice == "ask_user":
            return ask_user(p.signals)
        if p.stuck:
            agent.add_hint(f"You seem stuck: {p.signals[0]}. Try something different.")
```

**LangGraph:** pass `state["messages"]`. Tool calls and tool results are paired by ID:

```python
p = check_progress(state["messages"], goal=state["task"])
```

`loop_signals` is cheap enough to run on every step. For example, call `check_progress` only when `loop_signals` returns something.

## Input

| You pass | Each step is |
|---|---|
| A list of dicts | `tool` (or `action`, `name`), `args` (or `input`, `arguments`), `result` (or `output`, `observation`), `error`, and optionally `state` |
| OpenAI chat messages | Each `tool_calls` entry, paired with its `role: "tool"` message by `tool_call_id` |
| Anthropic messages | Each `tool_use` block, paired with its `tool_result` by `tool_use_id`. `is_error` marks an error. |
| LangChain or LangGraph messages | Each `AIMessage.tool_calls` entry, paired with its `ToolMessage`. `status="error"` marks an error. |
| A jevbrief trace (`.jsonl`) | Each decision. The chosen option is the action, and the state fingerprint is the result. With several runs in one file, the latest run is used. |

A `state` is anything that describes where the agent is, such as a page URL, a game position, or a hash of its memory. When you pass one, "new information" means a new state. Otherwise it means a new result.

## What Jev sees

Loops are counted in code, because Jev is weak at counting. Jev gets the counts as words, plus the last few steps:

| Signal | Example |
|---|---|
| `repeat` | `search_code called 5 times in a row with the same arguments, the same result each time` |
| `repeat_total` | `merge_pull_request called 5 times with the same arguments and the same result in the last 20 steps` |
| `errors` | `the same error 4 times: 409 Conflict: branch fix-invoice is behind main`, with how many failed in a row |
| `cycle` | `a cycle repeated 3 times: git_status -> git_diff` |
| `novelty` | `new information in 1 of the last 8 steps`, with the steps since the last new information |
| `step` | The last 6 steps, oldest first: the tool, short arguments, and a short result or error |

Some repeats are progress, not loops, and the counting keeps them apart:
- **Paging:** the same tool with new arguments each call.
- **Polling:** the same call with a new result each time ("a different result each time"). `loop_signals` does not list it.
- **A single retry:** anything seen fewer than 3 times.

## Reason codes

| Code | Meaning |
|---|---|
| `steps.old` | A step before the most recent `recent` steps |
| `steps.weak_signal` | A pattern seen fewer than 3 times, such as one retry |
| `steps.loop` | Kept: a repeat, cycle, or error pattern (+0.3) |
| `steps.recent` | Kept: one of the most recent steps |
| Core | `unlabeled`, `low_score`, `budget` |

## Options

`check_progress(history, goal, window=20, recent=6, trace="traces/progress.jsonl", min_confidence=0.5)`. It also accepts any `Briefing` argument, such as `jev`, `model`, or `trace_level`.

`loop_signals(history, window=20)`.

With the adapter directly: `StepsAdapter({"window": 20, "recent": 6})`.

## Question pack

`verdict` asks three questions in one call:

- **The verdict,** a Choice: `progressing`, `stuck_repeating`, `stuck_failing`, or `done`. This drives `p.verdict` and `p.stuck`.
- **`stuck`,** a Noul: is the agent stuck, without getting closer to the goal? This is `p.probability`.
- **`advice`,** a Choice: `continue`, `change_arguments`, `try_different_tool`, `ask_user`, or `stop`. This is `p.advice`.

When the verdict is below `min_confidence`, `p.verdict` is `None`, and `p.stuck` comes from the probability instead.

## Benchmark

[bench/steps/results.md](../../bench/steps/results.md): 28 synthetic agent histories, each 10 to 30 tool calls using real GitHub MCP tool names, run 3 times each.

| Arm | Verdict accuracy | Median input tokens |
|---|---|---|
| raw (every step, no counting) | 89% | 2,506 |
| jevbrief (counted signals + last 6 steps) | **93%** | **1,266** (−49%) |

`loop_signals` alone, with no Jev call, separated stuck from not stuck on all 28, so on this set the counting does most of the work. Jev adds the four-way verdict and the advice. Two of the three misses are arguable labels; the results file explains each.

## Limits

- **It reads what happened, not what should happen.** It cannot tell that a plan is wrong while every step brings new results. An agent that reads a new wrong file each time looks like it is progressing.
- **Results are compared exactly.** Two results that differ only by a timestamp count as new information. Pass a `state` when you have a better measure of progress.
- **Synthetic benchmark.** The histories were written while building the adapter.
