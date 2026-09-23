# jevbrief v0.1 — Build spec
> Turn a web page into a clean, small briefing for Jev, and record exactly what was dropped and why.

jevbrief is a Python SDK that converts raw sources into compact state for TypeSafe's Jev model, filters out noise with deterministic rules, and writes a trace of every kept and dropped fact with a reason code. v0.1 supports one source (web pages via Playwright) and ships **Thursday, September 24, 2026**.

---

## How to use this spec (instructions for Claude Code)

- Read this whole file before writing code. It is the source of truth. If something here conflicts with a later instruction from the user, ask.
- Build in the order given in "Build order and checkpoints". Stop at each checkpoint and run its check before moving on.
- Keep it minimal. Standard library first. The only runtime dependencies allowed are `playwright` and the TypeSafe Python SDK. Ask before adding any other dependency.
- No speculative features. Anything listed under "Non-goals" must not be built, even partially.
- Write user-facing text (README, CLI help, viewer labels, launch post) in plain, normal English, even if terse output mode is active in chat.
- Verify the TypeSafe SDK interface against the installed package before relying on the example calls below. The examples come from docs and may differ in detail.
- Never print, log, or commit the API key. It is read from `TYPESAFE_API_KEY`.

---

## Goals

1. Extract interactive elements from a web page into a common fact format.
2. Filter facts with deterministic salience rules. Every dropped fact gets a reason code.
3. Fit the kept facts into a token budget, flagging facts cut only for space.
4. Skip Jev calls when the state has not changed (fingerprint).
5. Ask Jev "which element should be clicked next for this goal?" as a Choice question.
6. Write one trace record per decision to JSONL.
7. Render traces in a single-file HTML viewer that shows kept facts, dropped facts with reasons, and Jev's answer.
8. Prove value with a benchmark comparing raw state against jevbrief state on accuracy, tokens, and latency.

## Non-goals (do not build in v0.1)

- TypeScript version
- Game, log, chat, robotics, or any adapter other than DOM
- Genre packs, config-file mappings, plugin systems
- Live streaming mode, WebSocket server, replay, "what if" re-asking
- Backends other than the native TypeSafe API
- CI regression checks, calibration tooling, hosted anything

---

## Constraints from Jev that shape the design

| Constraint | Design consequence |
|---|---|
| Text-only input | Everything must be serialized to compact JSON |
| Choice question max 255 options | Budgeter hard-caps candidates at 255, default target 60 |
| Context limit 32k tokens (state plus longest question) | Default token budget 2,000; hard limit 30,000 |
| Weak at arithmetic, counting, dates | Code computes all numbers; Jev only chooses |
| Irrelevant context lowers accuracy | Salience filter drops noise before the call |
| `jev-latest` can change | Pin `jev-1.13.0` and record the model in every trace |

---

## Repository layout

```text
jevbrief/
  jevbrief/
    __init__.py
    facts.py          # Fact dataclass, reason codes
    dom.py            # Playwright extractor -> list[Fact]
    salience.py       # scoring + dropping with reasons
    budget.py         # token estimate + cut to budget
    fingerprint.py    # stable hash of kept state
    questions.py      # next_click Choice builder + answer mapping
    jev.py            # thin wrapper around the TypeSafe SDK
    trace.py          # TraceRecord + JSONL writer
    brief.py          # Brief pipeline object tying it together
    cli.py            # `jevbrief` command (argparse)
    viewer.html       # single-file trace viewer template
  bench/
    tasks.json        # benchmark tasks
    run_bench.py
  fixtures/           # saved HTML snapshots of benchmark test pages (repo root)
  docs/               # this spec and the setup runbook
  examples/
    click_agent.py
  tests/
  README.md
  LICENSE             # MIT
  pyproject.toml
```

---

## Data model

### Fact

```python
@dataclass
class Fact:
    id: str              # stable, e.g. "e14"; used as the Choice option key
    kind: str            # "button" | "link" | "input" | "select" | "text"
    label: str           # visible text, aria-label, placeholder, or alt; trimmed to 80 chars
    attrs: dict          # small extras: {"type": "submit", "href_path": "/cart"}
    visible: bool
    enabled: bool
    in_viewport: bool
    y: int               # page y position in px, computed in code
    score: float = 0.0   # set by salience
    kept: bool = True
    reason: str = ""     # reason code if dropped, rule name if kept
```

Stable IDs come from a hash of tag, label, and DOM path so the same element keeps the same ID across ticks.

### Reason codes

| Code | Meaning |
|---|---|
| `hidden` | Not visible (display none, visibility hidden, aria-hidden, zero size) |
| `disabled` | Element is disabled |
| `not_interactive` | Plain text with no link to the goal |
| `unlabeled` | No usable label, so Jev could not tell what it is |
| `duplicate` | Same kind and label as a higher-scored fact |
| `low_score` | Scored below the keep threshold |
| `budget` | Would have been kept, cut only to fit the token or option budget |

Kept facts record the top rule that raised their score, for example `goal_match` or `in_viewport`.

### TraceRecord (one JSONL line per decision)

```json
{
  "ts": "2026-09-23T20:14:03Z",
  "run_id": "r_8f2c",
  "tick": 3,
  "source": {"adapter": "dom", "url": "https://example.com/product", "raw_facts": 212},
  "goal": "add this item to the cart",
  "facts": [ {"id": "e14", "kind": "button", "label": "Add to cart", "score": 0.92, "kept": true, "reason": "goal_match"} ],
  "budget": {"limit_tokens": 2000, "used_tokens": 640, "cut_for_budget": 0},
  "fingerprint": {"hash": "a91c...", "changed": true, "reused_tick": null},
  "jev": {"model": "jev-1.13.0", "question": "next_click", "choice": "e14", "confidence": 0.88, "probabilities": {"e14": 0.88, "e2": 0.05}, "latency_ms": 212},
  "outcome": "applied"
}
```

`outcome` is one of `applied`, `reused`, `low_confidence`, `error`. Trace levels: `off`, `summary` (default, facts store only id, kept, reason), `full` (all fact fields plus the state sent).

---

## Pipeline behavior

### 1. DOM extraction (`dom.py`)

Run one `page.evaluate()` script that collects `a`, `button`, `input`, `select`, `textarea`, `[role=button]`, `[role=link]`, `[onclick]`, plus headings as `text` facts. For each element, return tag, label, visibility, enabled state, bounding box, and a short DOM path. Do all filtering in Python, not in the browser script, so reasons are recorded.

### 2. Salience (`salience.py`)

Deterministic scoring. Start every fact at 0.5, then apply:

| Rule | Effect |
|---|---|
| Hidden | Drop, `hidden` |
| Disabled | Drop, `disabled` |
| No label | Drop, `unlabeled` |
| Text fact with no goal word | Drop, `not_interactive` |
| Goal word appears in label | +0.35, rule `goal_match` |
| In viewport | +0.10, rule `in_viewport` |
| Far below viewport (more than 3 screens) | -0.20 |
| Duplicate kind and label | Drop lower score, `duplicate` |
| Final score below 0.3 | Drop, `low_score` |

Goal words are lowercase words from the goal minus a short stopword list. Users can pass `pins=["e14"]` to force-keep facts.

### 3. Budget (`budget.py`)

Estimate tokens as `len(json_string) / 4`, no tokenizer dependency. Sort kept facts by score, keep until the token budget or the option cap (default 60, hard max 255) is hit. Mark the rest `budget`.

### 4. Fingerprint (`fingerprint.py`)

SHA-256 of the canonical JSON (sorted keys) of kept facts plus the goal. If it equals the previous tick's hash, reuse the last decision and set `outcome` to `reused`.

### 5. Question and call (`questions.py`, `jev.py`)

Build one Choice question. Options are kept fact IDs, each described as `"{kind}: {label}"`. Example call shape (confirm against the installed SDK):

```python
from typesafe_sdk import TypeSafeClient, Choice

client = TypeSafeClient()
resp = client.system_one(
    model="jev-1.13.0",
    state=brief.state_json(),
    questions={"next_click": Choice(
        instructions=f"Which element should be clicked next to: {goal}",
        criteria={f.id: f"{f.kind}: {f.label}" for f in kept},
    )},
)
ans = resp.answers["next_click"]   # .choice, .confidence, .probabilities
```

Map the chosen ID back to the Fact. If confidence is below the caller's `min_confidence` (default 0.5), set `outcome` to `low_confidence` and return no action. On any API error, record `error` and return no action.

### 6. Public API (`brief.py`)

```python
from jevbrief import Brief

brief = Brief(goal="add this item to the cart", budget_tokens=2000, trace="trace.jsonl")
facts = await brief.from_page(page)       # extract + salience + budget
decision = brief.next_click()             # fingerprint + Jev + trace
if decision.fact:
    await page.locator(decision.fact.selector).click()
```

Keep a `selector` on each fact internally so the example agent can click it.

---

## CLI

```bash
jevbrief inspect https://example.com --goal "add to cart"   # print kept and dropped facts, no Jev call
jevbrief ask https://example.com --goal "add to cart"       # one full decision, writes trace
jevbrief view trace.jsonl                                   # open viewer in browser
jevbrief bench bench/tasks.json                             # run the benchmark
```

Use `argparse`. `inspect` must work without an API key, since it is the zero-cost way to try the tool.

---

## Trace viewer

`jevbrief view` reads the JSONL, injects it as JSON into `viewer.html`, writes a temp file, and opens it with `webbrowser`. No server, no build step, no external scripts.

- **Left panel:** list of decisions with tick, goal, outcome, and confidence. Color by confidence (green 0.8 and up, amber 0.5 to 0.8, red below 0.5 or error).
- **Right panel for the selected decision:** Jev's choice and confidence at the top, a probability bar per option, then kept facts, then dropped facts greyed out and grouped by reason code with counts.
- **Flags:** show a warning badge when any fact was cut with `budget`, and when confidence is below 0.5.
- Support light and dark mode with `prefers-color-scheme`.

---

## Benchmark

`bench/tasks.json` holds 8 to 10 tasks. Each task has a saved HTML fixture (for repeatability), a goal, and the expected label of the correct element.

```json
[{"fixture": "../fixtures/shop_product.html", "goal": "add this item to the cart", "expected_label": "Add to cart"}]
```

For each task run two arms, three times each:

- **raw:** every extracted interactive element, no salience, in document order, capped at 255 options.
- **jevbrief:** the full pipeline.

Report a markdown table with accuracy, median state tokens, median latency, and median confidence per arm, and save all traces. Report the numbers honestly, including if the gain is small.

---

## Build order and checkpoints

### Thursday, September 24

1. `facts.py`, `trace.py`. Check: a TraceRecord round-trips through JSONL.
2. `dom.py`. Check: `jevbrief inspect` on one fixture lists sensible elements.
3. `salience.py`, `budget.py`, `fingerprint.py`. Check: unit tests for each reason code; `inspect` shows dropped facts with reasons.
4. `questions.py`, `jev.py`, `brief.py`. Check: `jevbrief ask` on one fixture returns the correct element and writes a trace.

5. Benchmark fixtures and `run_bench.py`. Check: results table prints for both arms.
6. If jevbrief is not clearly better, tune salience rules for at most 3 hours, then accept the result.
7. `viewer.html` and `jevbrief view`. Check: viewer opens a real trace and shows dropped facts by reason.
8. `examples/click_agent.py`. Check: agent completes a two-step task on a fixture.
9. README with the benchmark table, a GIF placeholder path, and a 10-line quick start.

10. Fresh-venv install test, `pytest` green, publish to PyPI as `jevbrief` 0.1.0, tag the release.

---

## Definition of done

- `pip install jevbrief` then `playwright install chromium` works in a clean environment.
- `jevbrief inspect` works with no API key.
- Every dropped fact in every trace has a reason code.
- The benchmark table is in the README with real numbers.
- The viewer opens with no network access.
- Tests cover every reason code and the fingerprint reuse path.
- README states: community project, not affiliated with TypeSafe AI.

---

## Launch checklist (tonight)

- Record a 30 to 60 second clip: the agent clicking through a page, then the viewer showing what Jev was told and what was dropped.
- X post: one-line pitch, the benchmark numbers, the clip, repo link, tag @typesafeai.
- Pitch line: "Other tools show what Jev decided. jevbrief shows what Jev was told, what it wasn't told, and why."
- Submit to the awesome-jev lists and shipwithjev.com, and post a Show HN.
- Reply to every comment and issue on launch day.

Ship target: v0.1.0 on PyPI and GitHub Thursday, September 24, 2026.
