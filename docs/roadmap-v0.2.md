# jevbrief v0.2+ roadmap: a source-neutral briefing SDK

Status: **draft for review**. No build code has been written for this plan.

jevbrief v0.1 turns a web page into a small, filtered briefing for Jev and records every dropped fact with a reason code. This plan turns the same idea into a core that works for any source, with web pages as the first of several adapters.

Guiding rules:

- **The core stays small.** Standard library only. Every adapter's dependencies are optional extras (`pip install jevbrief[nes]`), never required by the core.
- **Nothing that works today breaks.** The web API, CLI commands, and v0.1 trace files keep working unchanged.
- **Design the interface from real adapters, not guesses.** The adapter interface stays marked experimental until at least three adapters (web, JSON, NES) use it.
- **TypeSafe's docs are the authority on Jev.** Adapters follow the docs' guidance: compute numbers, dates, and counts in code; send semantic values rather than raw numbers; filter irrelevant state before the call; one narrow judgment per question; include a "none" option when nothing may fit.

## Decisions (2026-09-24)

v0.1.0 has not been published, so the modular design ships **in v0.1.0 itself**. Later releases only add adapters and never change the core.

| Question | Decision |
|---|---|
| First stable release | **v0.1.0 = source-neutral core + `web` adapter + `json` adapter** |
| Release order after that | v0.2 NES, v0.3 OpenTelemetry logs, v0.4 Discord and Slack (renumbered from the sections below) |
| Reason codes | Core codes stay unprefixed (`hidden`, `disabled`, `unlabeled`, `duplicate`, `low_score`, `budget`). Adapter codes are namespaced (`web.not_interactive`, `nes.offscreen`) |
| Playwright | Optional extra: `pip install "jevbrief[web]"`. The core installs with only the TypeSafe SDK |
| JSON adapter config | TOML (with `tomli` on Python 3.10 in the `json` extra), JSON also accepted |
| NES scope | Super Mario Bros World 1-1 only |
| Chat | Export files only |
| Trace images | Saved in a folder next to the trace, embedded by the viewer when it builds the HTML |
| Compatibility | Nothing is published, so there is no v0.1 API to preserve. The web output (facts, scores, reasons) must stay identical, proven by snapshot tests |

Sections below that say "v0.2" for the core refactor now mean v0.1.0.

---

## 1. Audit: what assumes web pages today

Universal means it works for any source unchanged. Web means it only makes sense for web pages. Mixed means the idea is universal but the code or wording is web-specific.

### Fact (`facts.py`)

| Item | Status | Notes |
|---|---|---|
| `id`, `label`, `score`, `kept`, `reason` | Universal | |
| `attrs` (sent to Jev) | Universal | Already a free-form dict |
| `kind` values `button`, `link`, `input`, `select`, `text` | Web | The field is universal. The allowed values are web. `KINDS` constant is unused but web |
| `visible`, `enabled` | Mixed | Generic ideas ("observable", "actionable"), web defaults and wording |
| `in_viewport`, `y` | Web | Viewport and page position. Used only by web salience rules |
| `selector` | Web | CSS path, used to click |
| `box` | Mixed | Spatial box. Works for web and games, not for logs or chat |
| `fact_id(tag, label, path)` | Mixed | Stable hash is universal. The inputs are DOM terms |
| `clean_label`, 80-char limit | Universal | |
| `Fact.state()` | Universal | `id`, `kind`, `label`, plus attrs |
| `Fact.to_dict("summary")` | Universal | |

### Reason codes (`facts.py`)

| Code | Status | Notes |
|---|---|---|
| `unlabeled` | Universal | |
| `duplicate` | Universal | |
| `low_score` | Universal | |
| `budget` | Universal | |
| `hidden` | Mixed | Generic ("not observable now"), web description |
| `disabled` | Mixed | Generic ("cannot be acted on"), web description |
| `not_interactive` | Web | "Plain text with no link to the goal" is a DOM concept |
| Kept rules `goal_match`, `base`, `pinned` | Universal | |
| Kept rules `in_viewport`, `near_goal_input` | Web | |

The codes are a hard-coded tuple. There is no way to register new ones or attach descriptions to them.

### Salience (`salience.py`)

| Item | Status | Notes |
|---|---|---|
| Score-then-drop engine, base 0.5, keep threshold 0.3 | Universal | But it is one hard-coded function, not a rule list |
| `goal_words`, stopwords, plural stripping | Universal | English only |
| Hidden, disabled, unlabeled drops | Mixed | See reason codes |
| Text fact with no goal word | Web | |
| Goal match +0.35 | Universal | |
| In viewport +0.10, far below −0.25 | Web | Uses `in_viewport`, `y`, viewport height |
| Near goal input +0.20 | Web | Uses the CSS selector's parent path |
| Duplicate by `(kind, label)` | Universal | |
| Pins | Universal | |

### Budget and fingerprint (`budget.py`, `fingerprint.py`)

| Item | Status | Notes |
|---|---|---|
| Token estimate `len(json) / 4` | Universal | |
| Sort by score, cut to budget | Universal | Ties broken by `y`, which is web |
| Option cap 60, hard max 254 | Mixed | Only meaningful when the question's options are facts |
| Fingerprint of kept state plus goal | Universal | |

### Questions and Jev (`questions.py`, `jev.py`)

| Item | Status | Notes |
|---|---|---|
| One Choice question, options are fact IDs | Mixed | Web picks among facts. Games pick among actions, which are not facts |
| Wording "clicked or focused next" | Web | |
| `describe()` uses `href_path`, `type`, `filled` | Web | |
| `state()` has `goal`, `url`, `elements` | Mixed | `url` and `elements` are web names |
| `none` option | Universal | |
| `Jev.choice()` | Mixed | Only Choice, only one question per call. Noul, Score, and fan-out are not supported |

### Pipeline (`brief.py`)

| Item | Status | Notes |
|---|---|---|
| `Brief.from_page`, `from_page_sync`, screenshot | Web | |
| `Brief.load(facts, url, viewport_h)` | Mixed | Close to a generic entry point, but takes web arguments |
| `next_click()` | Web | Name and single question |
| `Decision.fact`, `choice`, `confidence`, `outcome` | Mixed | `fact` assumes the answer is a fact |
| Outcomes `applied`, `reused`, `low_confidence`, `error` | Universal | |
| Fingerprint reuse, min confidence, error handling | Universal | |

### Trace format (`trace.py`)

| Item | Status | Notes |
|---|---|---|
| `run_id`, `tick`, `ts`, `goal`, `facts`, `budget`, `fingerprint`, `outcome` | Universal | |
| `source.adapter = "dom"` | Universal | A good hook already exists |
| `source.url`, `source.raw_facts` | Mixed | `url` is web |
| `jev` holds one question | Mixed | No room for several questions or non-Choice answers |
| `page` (screenshot) | Mixed | An image is generic. Only web fills it |
| No schema version | Universal gap | Needed before the format changes |
| No reason-code descriptions in the trace | Universal gap | The viewer hard-codes them |

### Viewer (`viewer.html`, `viewer.py`)

| Item | Status | Notes |
|---|---|---|
| Rendering pipeline, decision list, filter, keyboard | Universal | |
| Probabilities, kept and dropped tables, reason groups | Universal | |
| Reason and kept-rule descriptions | Web | Hard-coded web wording |
| "What Jev saw" screenshot with boxes | Mixed | Spatial. Fits web and games, not logs or chat |
| Labels "elements on the page", `page(url)` helper | Web | |
| Help text | Web | |

### CLI (`cli.py`)

| Item | Status | Notes |
|---|---|---|
| `load_env`, `print_facts`, `view`, `latest_trace` | Universal | |
| `inspect`, `ask` | Web | Take a URL and start Chromium |
| `bench` | Web | Runs the web benchmark |
| `to_url`, `open_page`, `brief_page` | Web | |

### Benchmark (`bench.py`, `bench/`, `fixtures/`)

| Item | Status | Notes |
|---|---|---|
| Arms, repeats, medians, markdown table | Universal | |
| Raw arm = every non-text element | Web | |
| Task format `fixture`, `goal`, `expected_label` | Mixed | `expected_label` assumes the answer is a labeled fact |
| Playwright extraction, HTML fixtures | Web | |

### Other

| Item | Status |
|---|---|
| `playwright` is a required dependency | Web (the core does not import it at import time, which helps) |
| `examples/`, `fixtures/`, `tests/pages/`, `SKILL.md`, README | Web |

**Summary:** the data model, budget, fingerprint, outcomes, trace skeleton, and most of the viewer are already universal. The web coupling sits in five places: the fact's positional fields, the salience rules, the question wording and single-Choice assumption, the CLI entry points, and the benchmark.

---

## 2. Target design

### 2.1 Core concepts

```text
Source ──► Adapter.extract() ──► [Fact] ──► RuleSet ──► budget ──► fingerprint ──► QuestionPack ──► Jev ──► Decision + Trace
```

**Fact (universal).** Keep today's fields so existing code works, and split what is sent from what is not:

| Field | Meaning |
|---|---|
| `id`, `kind`, `label`, `score`, `kept`, `reason` | As today. `kind` becomes a free string declared by the adapter |
| `attrs` | Adapter-specific values **sent to Jev**. Must already be semantic (for example `"distance": "close"`, not `0x5A`) |
| `meta` | Adapter-specific values **not sent to Jev**: locator, position, raw values, timestamps. Rules and the viewer can read it |
| `visible`, `enabled` | Kept as universal "observable now" and "can be acted on", default `True` |
| `in_viewport`, `y`, `selector`, `box` | Kept on the dataclass for web compatibility. New adapters put the equivalents in `meta` |

**RuleSet (pluggable).** An ordered list of small rules replaces the single `score()` function:

```python
class Rule:
    name: str
    def apply(self, fact: Fact, ctx: RuleContext) -> Drop | Boost | None: ...

class GroupRule:            # rules that compare facts, such as duplicate
    def apply_all(self, facts: list[Fact], ctx: RuleContext) -> None: ...
```

- The core ships universal rules: `unlabeled`, `goal_match`, `duplicate`, `low_score`, pins, and the budget stage.
- Each adapter ships its own rules and a default `RuleSet`.
- Users can add, remove, or reorder rules: `web.rules().without("far_below").with_rule(MyRule())`.
- The web rule set reproduces today's behavior exactly. A regression test proves it on all fixtures before any refactor lands.

**Reason codes (extensible).** A registry of `code -> description`:

- Today's seven codes stay unprefixed and keep their meaning.
- Adapter codes are namespaced, `nes.offscreen` or `logs.below_severity`, so two adapters can never collide.
- Every trace record carries a `reasons` legend with the descriptions of the codes it uses, so the viewer is data-driven and needs no update for new adapters.

**QuestionPack (pluggable).** A pack builds one or more Jev questions from the goal and the kept facts, and maps the answers to a `Decision`.

- A pack chooses what the options are: kept facts (web: "which element?") or a fixed action set (games: "run right, jump, wait").
- A pack can ask several independent questions in one call, as the TypeSafe fan-out pattern recommends. For example, the web pack could ask `next_click` (Choice) and `task_done` (Noul) together.
- The pack names its primary question. Its answer fills `Decision.choice` and `Decision.confidence`. `Decision.fact` is set when the answer is a fact.
- Choice, Noul, and Score are all supported. `jev.py` becomes a thin `ask(state, questions) -> answers` wrapper.

**Briefing (engine).** A generic `Briefing(adapter, goal, ...)` runs the pipeline. `Brief` stays as the web wrapper with its current signature.

### 2.2 Adapter interface

```python
class Adapter(Protocol):
    name: str                          # "web", "json", "nes", "otel", "chat"
    reason_codes: dict[str, str]       # adapter codes and descriptions
    renderer: str                      # "spatial", "timeline", "thread", or "table"

    def extract(self, source, **options) -> Extracted: ...   # facts + context (url, frame, window, snapshot image)
    def rules(self) -> RuleSet: ...                          # default rules
    def questions(self) -> dict[str, QuestionPack]: ...      # packs; the first is the default
```

- **Viewer renderers are built in**, chosen by name: `spatial` (image plus boxes: web and NES), `timeline` (logs), `thread` (chat), and `table` (fallback, always works). Adapters pick one rather than shipping JavaScript. Custom renderers can come later if a real adapter needs one.
- **Discovery:** built-in adapters are registered in the core. Third-party packages register through a `jevbrief.adapters` entry point, so `pip install jevbrief-foo` adds an adapter without changes here.
- **CLI:** `jevbrief inspect <source> --adapter json --config mapping.toml --goal "..."`. `--adapter web` stays the default, so existing commands behave the same.

**Contributor template** (`adapters/_template/`, copied by contributors):

```text
jevbrief/adapters/<name>/
  __init__.py      # Adapter class, reason codes, renderer choice
  extract.py       # source -> [Fact]; all numbers turned into semantic values here
  rules.py         # adapter rules
  questions.py     # question pack(s)
tests/adapters/<name>/
  test_rules.py    # one test per reason code
  test_extract.py  # fixture in, facts out
  fixtures/
bench/<name>/tasks.json + fixtures
examples/<name>_example.py
docs/adapters/<name>.md
```

### 2.3 Backward compatibility

What must keep working, unchanged:

- `from jevbrief import Brief, Decision, Fact`, with the same constructor arguments.
- `Brief.from_page`, `Brief.from_page_sync`, `Brief.load`, `Brief.next_click`, `Brief.state`, `Decision.fact.selector`.
- `jevbrief inspect`, `ask`, `view`, and `bench` with today's arguments and output.
- Every v0.1 trace file opens in the viewer.
- `pip install jevbrief` still installs Playwright in 0.x (see open question 2).

Trace schema:

- v0.2 adds `"schema": 2` to every record. A record without `schema` is v1.
- v2 adds `adapter` (`{"name", "version"}`), `reasons` (legend), `answers` (every question in the call), and `context` (adapter-specific, replaces `source.url` and `page` for new adapters).
- v2 still writes `jev` for the primary question and `source.url` and `page` for web, so tools written against v1 keep working.
- `trace.read()` upgrades v1 records in memory. Old files are never rewritten.
- Golden v1 trace files are checked into `tests/traces/v1/`. A test renders each one in the viewer.

Web output regression:

- Before refactoring, record the facts, scores, and reasons for every web fixture into a snapshot file.
- After refactoring, the same inputs must produce identical output. The web benchmark is re-run and must match within noise.

### 2.4 Dependencies

| Install | Adds | Required by |
|---|---|---|
| `jevbrief` | `typesafe-sdk`, `playwright` (kept required in 0.x for compatibility) | Core and web |
| `jevbrief[json]` | Nothing on Python 3.11+. `tomli` on 3.10 if the config is TOML | JSON adapter |
| `jevbrief[nes]` | An NES emulator package (chosen during the NES spike) | NES adapter |
| `jevbrief[otel]` | Nothing for OTLP JSON files. `opentelemetry-proto` only if protobuf input is added later | Logs adapter |
| `jevbrief[chat]` | Nothing for export files. `slack_sdk` or `discord.py` only if live fetching is added later | Chat adapter |

Adapters import their extras lazily and fail with a clear message: `The nes adapter needs extra packages. Run: pip install "jevbrief[nes]"`.

---

## 3. Releases

Each adapter is its own release, and each release must ship all of the following. This is the definition of done for an adapter:

- [ ] Extractor
- [ ] Rules
- [ ] Question pack
- [ ] Reason codes
- [ ] Tests, including one per reason code
- [ ] Raw-versus-jevbrief benchmark, reported honestly
- [ ] Example
- [ ] README docs
- [ ] Viewer support
- [ ] SKILL.md section
- [ ] The web regression tests still pass

### v0.2.0: source-neutral core plus generic JSON adapter

The JSON adapter ships with the core because it proves the interface on a second source with no new dependencies.

**Core work:** `Rule`/`RuleSet`, reason registry, `QuestionPack`, generic `Briefing`, `Jev.ask()` with Choice, Noul, and Score plus fan-out, trace schema v2 with a v1 reader, a data-driven viewer (reason legend, `table` renderer), and `--adapter` in the CLI. Web moves to `jevbrief/adapters/web/` behind the unchanged `Brief`.

**JSON adapter:**

- **Input:** a JSON document or JSON Lines file, plus a mapping config.
- **Config** (TOML or JSON, see open question 3):

  ```toml
  items = "tickets[*]"                  # where the facts are
  id = "{id}"
  label = "{subject}"
  kind = "ticket"
  send = ["status", "priority", "customer_tier"]   # attrs sent to Jev

  [[rules]]                             # config rules become reason codes
  name = "closed"
  drop_if = { field = "status", equals = "closed" }

  [[rules]]
  name = "stale"
  drop_if = { field = "updated_days_ago", greater_than = 30 }   # compared in code

  [question]
  type = "choice"                       # choose among kept items, or fixed options
  instructions = "Which ticket should an agent handle next for: {goal}"
  ```

- **Rules:** the universal set plus config rules (`equals`, `in`, `greater_than`, `less_than`, `missing`, `matches`). Numbers and dates are compared in code, never by Jev.
- **Question pack:** `choose_item` (Choice over kept items plus `none`), `choose_option` (Choice over fixed options from the config), `check` (Noul).
- **Reason codes:** `json.<rule name>` for each config rule, plus `json.missing_field`.
- **Benchmark:** synthetic support-ticket queues and product catalogs. The raw arm sends every item and field. The jevbrief arm uses the config.
- **Example:** `examples/json_triage.py`, which picks the next ticket from a queue file.
- **Viewer:** `table` renderer.

Estimate: core refactor 3 to 4 days, JSON adapter 2 days, docs and benchmark 1 day. **About 1 to 1.5 weeks.**

### v0.3.0: NES emulator, Super Mario Bros mapping, platformer pack

- **Emulator:** a spike at the start compares Python NES emulators on Windows, macOS, and Linux: install without a compiler, frame stepping, RAM access, and frame buffer access. The winner becomes the only dependency of `jevbrief[nes]`.
- **ROM:** jevbrief never ships or downloads a ROM. Users supply their own legally obtained copy by path. Tests use small recorded RAM snapshots and a synthetic frame, not the ROM.
- **Mapping:** a Super Mario Bros RAM map (player position and state, enemy slots with type, active flag, and position, level and timer), taken from the community-documented RAM map and verified against the emulator during the spike.
- **Extractor:** reads RAM once per decision tick and turns raw values into semantic facts in code, as the Jev docs require: `enemy: Goomba, ahead, close, same height`; `gap: ahead, medium`; `pipe: ahead, tall`. Jev never sees raw hex or pixel coordinates.
- **Rules:** `nes.inactive` (empty enemy slot), `nes.offscreen`, `nes.behind_player` (already passed), `nes.far_ahead`, plus universal duplicate and budget.
- **Platformer pack:** `next_action`, a Choice over a fixed action set (`run_right`, `jump_right`, `short_hop`, `wait`, `run_left`) with a description of what each action does. Optionally `danger_ahead` (Noul) in the same call. The chosen action is held for a set number of frames, and the emulator is paused while Jev answers, so API latency does not affect play.
- **Benchmark:** World 1-1 over a fixed number of decisions. Metrics: distance reached, deaths, level completion, input tokens, latency. Raw arm: every RAM-derived object with raw numbers. jevbrief arm: filtered semantic facts.
- **Example:** `examples/nes_mario.py --rom path/to/your.nes`.
- **Viewer:** `spatial` renderer with the frame and boxes around objects, reusing the web viewer. Frames are encoded as PNG with a small standard-library writer, so no image library is needed.

Estimate: emulator spike 1 day, mapping and extractor 2 days, pack and tuning 2 to 3 days, benchmark and demo 1 to 2 days. **About 1.5 to 2 weeks.** This is the riskiest adapter (see risks).

### v0.4.0: OpenTelemetry logs

- **Input:** OTLP JSON export files (logs, plus optional spans). Standard library only.
- **Extractor:** groups log records into facts by message template (numbers and IDs replaced with placeholders), service, and severity. Counts, first and last seen, and "started after deploy" are computed in code and sent as buckets (`count: many`, `started: after deploy`).
- **Rules:** `logs.below_severity`, `logs.healthcheck` (configurable patterns), `logs.outside_window`, `logs.single_occurrence`, plus universal duplicate and budget.
- **Question pack:** `likely_cause`, a Choice over kept error groups plus `none`. Optional `user_facing` Noul per group and a `severity` Score.
- **Benchmark:** synthetic incidents with a known injected cause, buried in realistic noise. Raw arm: the most recent N raw log lines that fit the context. jevbrief arm: grouped and filtered.
- **Example:** `examples/otel_incident.py`, which finds the likely cause in an exported log file.
- **Viewer:** `timeline` renderer with groups on a time axis and dropped groups greyed.

Estimate: **about 1 week.**

### v0.5.0: Discord and Slack chat

- **Input:** export files only in v0.5 (Slack workspace export JSON; Discord JSON from a standard exporter). No tokens, no network, no new dependencies.
- **Extractor:** messages and threads become facts: author role (not name, by default), age bucket, reply count, reactions, thread position.
- **Rules:** `chat.bot`, `chat.system` (joins, pins), `chat.reaction_only`, `chat.deleted`, `chat.off_topic`, `chat.outside_window`, plus universal duplicate and budget.
- **Question pack:** `answering_message` (Choice: which message answers the question, plus `none`), `needs_reply` (Noul per thread), `urgency` (Score).
- **Privacy defaults:** author names replaced with stable pseudonyms, emails and phone numbers redacted before anything reaches Jev or the trace, and a clear warning in the docs about consent and workspace policies.
- **Benchmark:** synthetic support channels with known answers.
- **Example:** `examples/chat_answer_finder.py`.
- **Viewer:** `thread` renderer.

Estimate: **about 1 week**, plus review time for the privacy defaults.

---

## 4. ADAPTERS.md contributor guide (outline)

To be written alongside v0.2.0, once the interface exists:

1. What an adapter is, and the pipeline diagram.
2. The five-minute path: copy `adapters/_template/`, rename it, and run `pytest tests/adapters/<name>`.
3. Writing an extractor: stable IDs; `attrs` versus `meta`; turning numbers, dates, and counts into semantic values in code.
4. Writing rules: `Drop` versus `Boost`, naming reason codes (`<adapter>.<code>`), and one test per code.
5. Writing a question pack, following TypeSafe's guidance: one narrow judgment per question; options described so they are clearly different; a `none` option; fan-out for independent questions; thresholds tuned on your own data.
6. Choosing a viewer renderer.
7. Adding optional dependencies as an extra, with lazy imports and a clear install message.
8. Writing an honest benchmark: a raw arm, fixed tasks, repeats, and caveats in the results.
9. The adapter definition of done (the checklist in section 3).
10. Review process and how releases are cut.

### "Good first adapter" issue ideas

Each is small, needs no new dependencies, and has an obvious raw-versus-jevbrief benchmark:

- **CSV or spreadsheet rows:** a thin layer over the JSON adapter.
- **RSS and Atom feeds:** "which article answers my question?" using the standard library XML parser.
- **Android UI hierarchy:** `uiautomator` XML dumps, the mobile version of the web adapter.
- **Terminal and TUI screens:** text screen captures, "which menu item next?"
- **Kubernetes events:** `kubectl get events -o json`, "which event explains the failing pod?"
- **Git pull request files:** a diff summary, "which file should a reviewer read first?"
- **Home Assistant states:** entity JSON, "which device is relevant to this request?"
- **Email mailbox:** an mbox file, "which email needs a reply?"

---

## 5. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Over-abstraction before real adapters exist | A heavy interface that fits no adapter well | Build from web plus JSON only. Mark the interface experimental until NES lands. Keep `Rule` and `QuestionPack` to one method each |
| Breaking v0.1 users during the refactor | Lost trust at launch | Web snapshot tests and golden v1 traces written before any refactor; the benchmark re-run must match |
| NES emulator packages: native builds, Windows wheels, maintenance | The adapter cannot install for many users | A spike before committing; fall back to a documented "bring your own emulator" hook that only needs RAM and frame access |
| ROM legality | Legal exposure | Never ship, download, or link ROMs. Tests use RAM snapshots and synthetic frames. Docs require a legally obtained copy |
| Jev on game state: timing, spatial reasoning, numbers | Poor play, a weak demo | Semantic buckets computed in code, a small fixed action set, paused emulator, honest benchmark even if weak |
| Chat privacy (personal data, consent, workspace policy) | Harm to users, legal exposure | Export files only, pseudonymized authors, redaction by default, prominent docs warning |
| Reason-code sprawl | A confusing viewer | Namespaced codes, required descriptions, a legend in every trace |
| Benchmarks on synthetic data overstate value | Credibility | Publish tasks and caveats; invite real-data contributions; never claim gains that were not measured |
| Maintenance load from many adapters | Slower releases | Adapters beyond these four live in separate packages through entry points |
| Jev model changes | Thresholds drift | Pin `jev-1.13.0` per adapter; record the model in every trace; re-run benchmarks on upgrade |

## 6. Open questions for the owner

1. **Reason-code names:** namespaced (`nes.offscreen`, recommended) or flat (`offscreen`)?
2. **Playwright:** keep it required in 0.x for compatibility (recommended), or move it to `jevbrief[web]` in 0.2 with a clear error message?
3. **JSON adapter config format:** TOML (needs `tomli` on Python 3.10) or JSON (no dependency), or both?
4. **NES scope:** is Super Mario Bros World 1-1 enough for v0.3, or do you want a second game to prove the mapping format?
5. **Chat:** export files only in v0.5 (recommended), or live Slack and Discord APIs as well?
6. **Trace size:** screenshots and frames make traces large. Keep images inline in JSONL, or write them to a folder next to the trace?
7. **Release v0.1.0 first?** PyPI still has the 0.0.1 placeholder. Publishing 0.1.0 before the refactor gives users a stable version to compare against.

## 7. Time estimates

| Release | Scope | Estimate |
|---|---|---|
| v0.1.0 | Publish what is built (rebuild, fresh install test, upload, tag) | 1 hour |
| v0.2.0 | Core refactor, schema v2, data-driven viewer, JSON adapter, ADAPTERS.md, template | 1 to 1.5 weeks |
| v0.3.0 | NES adapter, Super Mario Bros mapping, platformer pack, demo | 1.5 to 2 weeks |
| v0.4.0 | OpenTelemetry logs adapter, timeline renderer | About 1 week |
| v0.5.0 | Discord and Slack chat adapter, thread renderer, privacy defaults | About 1 week |

About **5 to 6 weeks** in total at a steady pace. The NES estimate has the widest range because of the emulator spike.
