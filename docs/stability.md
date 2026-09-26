# Stability and changes

jevbrief is below 1.0, so a minor release (0.8, 0.9) can change the API. When it does, the change is listed here with what to do, and the old way keeps working for at least one release where possible.

## What is stable

These are used by applications and are kept compatible:

- `Briefing(adapter, goal, ...)`, `extract()`, `load()`, `decide()`, `adecide()`, `kept`, `facts`, and `state()`
- `Decision` and its four outcomes: `applied`, `reused`, `low_confidence`, and `error`
- `select_tools`, `pick_tool`, `apick_tool`, `check_progress`, `acheck_progress`, and `loop_signals`
- the web `Brief`: `from_page`, `from_page_sync`, `next_click`, and `anext_click`
- every adapter's name, reason codes, and fact IDs. The same source gives the same IDs across releases
- the trace format (`schema` 1) and the CLI commands and their flags

The adapter interface (`Adapter`, `Extracted`, `Rule`, `RuleSet`, and question packs) can still change in a minor release. When it does, adapters written for the previous release keep working.

## 0.8.0

An engineering release: no new adapter. Every published benchmark gives the same facts and states as in 0.7.0.

**New**
- **Async:** `await brief.adecide()`, `await apick_tool(...)`, `await acheck_progress(...)`, and `await brief.anext_click()`. They return the same results as the sync versions without blocking the event loop.
- **`Jev(model, timeout=..., retries=...)`:** a timeout and retries with backoff, for both the sync and the async client. You can also pass your own SDK clients, and close them with `close()` and `aclose()`.
- **`jevbrief inspect --json` and `jevbrief ask --json`**, for scripts and CI.
- **`jevbrief bench --workers N --write results.md`:** Jev calls run in parallel (default 4), and the results tables can be saved to a file.
- **Typed:** the package ships `py.typed`, and mypy passes on it.

**Fixed**
- Config or options passed to `extract()`, such as `extract(logs, min_severity="error")` or `extract(data, config="map.toml")`, were ignored by the rules. They now apply.
- `jevbrief bench` crashed on a Windows console when a task name held a character the console could not print.
- The json adapter now rejects an invalid `now` date at once, with a clear message.

**Changed**
- **Errors:** only Jev and network failures give `outcome="error"`. That means the SDK's `TypeSafeError` (which covers a missing API key, rate limits, and timeouts) and `OSError`. Any other exception is a bug, in an adapter, a rule, or your code, and is now raised instead of being recorded as an error.

**For adapter authors**
- The base `Adapter` constructor registers `reasons` and loads the config (a dict, `.toml`, or `.json`). Set `takes_config = False` if yours takes none.
- `rules(self, options=None)` receives the keyword arguments of the latest `extract()`. Read settings with `self.settings(options)` instead of storing options on the adapter. `rules(self)` still works.
- Pass `Extracted(..., raw=[...])` when the benchmark's raw arm needs more than the facts, instead of keeping the last extraction on the adapter. `raw(facts)` still works.
- New shared helpers: `jevbrief.sources.load_config` and `find_files`, and `jevbrief.text.template` and `frequency`.
- Import the core rules by name (`from jevbrief.rules import hidden, goal_match, ...`) instead of unpacking `CORE_RULES`, which still exists.

See [ADAPTERS.md](../ADAPTERS.md) and the adapter template in `contrib/adapter_template/`.
