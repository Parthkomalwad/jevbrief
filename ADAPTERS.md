# Writing a jevbrief adapter

An adapter teaches jevbrief to read a new kind of source: a game, a log file, a chat export, a mobile screen. The core does the rest: rules, budget, fingerprint, the Jev call, traces, and the viewer.

Adding an adapter never changes the core or other adapters. Removing one is deleting its folder and its extra.

```text
your source ──► Adapter.extract() ──► facts ──► rules ──► budget ──► question pack ──► Jev ──► trace + viewer
                 (you write this)               (you pick)           (you write this)
```

## Before you start

1. Search the [adapter requests](https://github.com/parthkomalwad/jevbrief/issues?q=label%3Aadapter-request) to see if someone asked for it.
2. Open a **New adapter proposal** issue (it asks the questions below). A maintainer will reply with any design notes before you write code.

## The five-minute path

```bash
git clone https://github.com/parthkomalwad/jevbrief && cd jevbrief
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp -r contrib/adapter_template jevbrief/adapters/mysource
cp contrib/test_adapter_template.py tests/test_mysource.py
```

Rename `mysource` everywhere, add the adapter to `BUILTIN` in `jevbrief/adapters/__init__.py` and to `[project.entry-points."jevbrief.adapters"]` in `pyproject.toml`, then run `pytest tests/test_mysource.py`.

Prefer a separate package? Publish `jevbrief-mysource` with the same entry point in its own `pyproject.toml`. jevbrief finds it automatically.

## 1. Extract facts

`extract(source, **options)` returns an `Extracted(facts, source={...}, image=None, image_size=None)`.

Each `Fact` has:

| Field | What to put there |
|---|---|
| `id` | Stable across ticks for the same thing. Use `fact_id(...)` over identifying parts, or the source's own ID |
| `kind` | A short type name you choose (`enemy`, `log_group`, `message`) |
| `label` | What a person would call it, 80 characters max. No label means it is dropped as `unlabeled` |
| `attrs` | Values **sent to Jev**. Keep them few and semantic |
| `meta` | Values **not sent**: raw numbers, positions, locators, timestamps. Rules and the viewer can read `meta` |
| `visible`, `enabled` | Set to `False` when the thing is not observable, or cannot be acted on. Core rules drop these |

**The most important rule:** Jev is weak at arithmetic, counting, dates, and raw numbers (see TypeSafe's [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md)). Do that work in `extract()` and send named values instead:

| Instead of | Send |
|---|---|
| `"x": 212, "player_x": 180` | `"distance": "close", "side": "ahead"` |
| `"updated_at": "2026-09-01T09:00:00Z"` | `"updated": "this week"` |
| `"count": 1843` | `"frequency": "very often"` |
| `"color": "#ff0000"` | `"color": "red"` |

For a spatial source (screens, games), put `meta["box"] = [x, y, width, height]`, return an `image` (JPEG or PNG bytes) with its `image_size`, and set `renderer = "spatial"`. The viewer then draws boxes on the image.

## 2. Choose rules

Start from the core rules and add your own:

```python
from jevbrief.rules import CORE_RULES, Boost, Drop, Rule, RuleSet

hidden, disabled, unlabeled, goal_match, duplicate = CORE_RULES
offscreen = Rule("mysource.offscreen", lambda f, ctx: Drop("mysource.offscreen") if f.meta["x"] < 0 else None)

def rules(self):
    return RuleSet([hidden, disabled, unlabeled, offscreen, goal_match, duplicate])
```

- A rule returns `Drop(reason)`, `Boost(delta, name)`, or `None`. A `GroupRule` sees all facts (for duplicates or neighbors).
- Name every reason code `<adapter>.<code>` and give it a plain description in the adapter's `reasons` dict. Core codes (`hidden`, `disabled`, `unlabeled`, `duplicate`, `low_score`, `budget`) are shared.
- Every drop must have a reason. That is what makes a wrong answer debuggable.
- Users can change your rules without forking: `adapter.rules().without("mysource.offscreen").with_rule(...)`.

## 3. Write a question pack

A pack builds Jev questions from the kept facts. Follow TypeSafe's [question guidance](https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md):

- **One narrow judgment per question.** "Which enemy should Mario avoid next?" not "What should Mario do and why?"
- **Describe each option so it is clearly different** from the others.
- **Include a "none" option** when nothing may fit. `FactChoice` adds one for you.
- **Independent questions go in the same call** (the fan-out pattern), for example a Noul "is there danger ahead?" next to the main Choice.

```python
from jevbrief import FactChoice, OptionChoice

# Options are facts: "which of these?"
FactChoice("pick_group", "Goal: {goal}\nWhich log group in `items` most likely explains this?")

# Options are fixed actions: "what now?"
OptionChoice("next_action", "Goal: {goal}\nWhat should the player do next?",
             {"run_right": "Keep running right", "jump": "Jump now", "wait": "Stand still"},
             extra={"danger": {"type": "noul", "instructions": "Is an enemy about to touch the player?"}})
```

Return packs from `packs()`. The first one is the default. Users pick another with `--pack`.

Override `state(goal, kept, source)` to control the exact JSON sent to Jev. Use named fields.

## 4. Test it

Every adapter must pass the shared contract:

```python
from jevbrief.testing import check_adapter

def test_contract():
    check_adapter(MySourceAdapter(), "tests/fixtures/mysource/sample.json", goal="find the error")
```

It runs the pipeline with a fake Jev (no API key) and checks stable unique IDs, registered and namespaced reason codes, a JSON-serializable state within budget, valid questions, and a trace the viewer can render.

Also add **one test per reason code** your adapter defines.

## 5. Benchmark it honestly

Add `bench/mysource/tasks.json` and fixtures, then `jevbrief bench bench/mysource/tasks.json`.

- `adapter.raw(facts)` defines the raw arm: what a naive integration would send.
- Tasks use `expected_choice` (an option key or fact ID) or `expected_label`.
- Report the table in `bench/mysource/results.md` with its caveats: synthetic data, anything tuned after seeing results, small sample sizes. Never claim a gain you did not measure.

## 6. Dependencies

- The core must never import your adapter, and your adapter must not be imported at `import jevbrief`.
- Put third-party packages in an extra: `mysource = ["somepackage>=1.0"]` in `pyproject.toml`.
- Import them inside your methods and call `need("mysource", "somepackage")` first, so users see: `Run: pip install "jevbrief[mysource]"`.

## Definition of done

- [ ] Extractor, rules, question pack, reason codes with descriptions
- [ ] `check_adapter` passes, plus one test per reason code
- [ ] Benchmark tasks and `results.md` with caveats
- [ ] An example in `examples/`
- [ ] Docs in `docs/adapters/<name>.md` and a row in the README's adapter table
- [ ] Viewer renders its traces (`spatial` or `table`)
- [ ] Optional dependencies are an extra, imported lazily
- [ ] All existing tests still pass

## Good first adapters

Small, no new dependencies, and an obvious benchmark:

- **CSV or spreadsheet rows**, a thin layer over the json adapter
- **RSS and Atom feeds**: "which article answers my question?"
- **Android UI dumps** (`uiautomator` XML): the mobile version of the web adapter
- **Terminal screens**: "which menu item next?"
- **Kubernetes events** (`kubectl get events -o json`): "which event explains the failing pod?"
- **Git pull request files**: "which file should a reviewer read first?"
- **Home Assistant states**: "which device is this request about?"
- **Email mailbox** (mbox): "which email needs a reply?"
