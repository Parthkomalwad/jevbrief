# Next adapters: priority list

Written 2026-09-25, after v0.5.0, and updated 2026-09-26. It is for picking up the work in a new session: what to build, in what order, and what "done" means.

## Where things stand

- **Released adapters (8, v0.6.0):**
  - web, json, otel, and nes
  - ci: GitHub Actions and JUnit
  - tools: `select_tools` and `pick_tool`, with hybrid ranking
  - steps: `check_progress` and `loop_signals`
  - pr: review priority for a pull request (released in v0.6.0)
- **Done, not yet released:** the incident pack. otel also reads Kubernetes events and Alertmanager or Prometheus alerts (`bench/incident/`).
- **Docs site:** https://claude.ai/artifact/MpQRvn5d5bohrNVWwLVp31, built by `scripts/build_docs_site.py`.

## Priority list

| # | Adapter | Jev answers | Why now | Benchmark data | Size |
|---|---|---|---|---|---|
| 1 ✓ | `pr` (v0.6.0) | Which parts of this pull request need a human reviewer, and is it safe to merge? | Over 1 in 5 GitHub reviews now involve an agent. Agent PRs carry more duplication and debt. | **Real:** public PRs. Truth is which diff chunks got review comments or were reverted. | Medium |
| 2 ✓ | Incident pack (extend `otel`) | Which signal shows the root cause: a log group, a Kubernetes event, or an alert? | AI SRE is the hot category. Teams report 40–70% faster recovery, and evidence is scattered across logs, events, and alerts. | **Hard:** use the datasets behind the ARGUS and TriFleetRCA papers, or synthetic data | Medium |
| 3 | `android` | Which element to tap next | Mobile agents are growing. A screen has about 200 elements, and screenshots cost 5–10 times more tokens than the element list. | **Real:** AndroidWorld, Android in the Wild | Small to medium, since it reuses the web pattern |
| 4 | `vulns` | Which security alert to fix first, and which are noise | Teams get thousands of CVE alerts that match only on package name and version, and the real ones are buried. | **Real:** VEX-Bench (2026) | Medium |
| — | Skipped: RAG chunk selection | | Dedicated rerankers already do this well. jevbrief would be a weaker reranker. | | |

Also worth doing:
- **pr:** the benchmark was a tie on accuracy (55% against 55%, with 36% fewer tokens). Add merged PRs with no review comments so `safe_to_merge` can be scored, and measure large PRs separately.
- **Incident pack:** both otel sets are synthetic. Record a real one by injecting faults into a demo cluster (for example, the OpenTelemetry demo's fault flags) and exporting its logs, events, and alerts.
- **tools benchmark:** add Docker MCP servers (filesystem, memory, slack) with `bench/mcp/fetch_tools.py`, for a harder test with 300 or more tools.
- **steps benchmark:** replace the synthetic histories with real stuck agent traces as they become available.

## 1. `pr`: review priority for a pull request

- **Input:**
  - a unified diff, from `gh pr diff <n>` or a `.diff` or `.patch` file
  - optionally, the PR's JSON from the GitHub API (`/pulls/{n}` plus `/pulls/{n}/files`)
  - a folder containing both
- **Facts:** one per diff chunk (hunk). Each carries:
  - the file and its role: source, test, config, docs, generated, or lockfile
  - the size, as small, medium, or large
  - the change kind: added, removed, or modified
  - whether a matching test changed
  - what it touches: public API, auth or security, SQL, concurrency, or error handling

  Compute all of this in code, and send it to Jev as words.
- **Rules (reason codes `pr.<code>`):**
  - `pr.generated`: generated files and lockfiles
  - `pr.formatting_only`: only whitespace changed
  - `pr.rename_only`: the file was renamed with no other change
  - `pr.docs_only`: optional
  - `pr.vendored`: vendored third-party code
  - boosts: `pr.risky_area` and `pr.no_test`
- **Question pack:**
  - a Choice: which chunk most needs a human reviewer
  - an extra Noul: "safe to merge without changes?"
- **Benchmark:** collect merged PRs from active public repos (reuse `bench/ci/fetch_runs.py`'s GitHub client). Label with a known answer, in the same way as the ci collector: the chunks that got review comments (`/pulls/{n}/comments`), or later commits that touched the same lines.
  - **Raw arm:** the full diff.
  - **Watch out:** the ci work showed that automatic labels need a hand review.
- **Pairs with ci:** "the build broke, and this is the chunk that caused it."

## 2. Incident pack: extend `otel`

- Keep one adapter (`otel`) and one question (root cause). Add sources to the same timeline:
  - Kubernetes events: `kubectl get events -A -o json`
  - Prometheus or Alertmanager alerts: `/api/v2/alerts` JSON
  - optionally, deploy history
- **Facts:** event groups (reason and object kind, such as `BackOff Pod`) and alerts (alert name, severity, how long it has been firing), on the same timeline as log groups.
- **Rules:**
  - `otel.routine_event`: Scheduled, Pulled, Created, and Started events
  - `otel.resolved_alert`: alerts that are already resolved
  - boost: signals at the incident start
- **The viewer:** the timeline viewer already exists. Add a source label or color per kind.

## 3. `android`: next tap on a mobile screen

- **Input:** `uiautomator dump` XML, Appium page source, or an AndroidWorld observation. A screenshot is optional, for the spatial viewer.
- **Facts:** one per element that can be clicked, focused, or scrolled. Each carries its text or content description, resource ID, bounds (converted to a position word), and whether it is enabled.
- **Rules:** `android.not_interactive`, `android.offscreen`, `android.decorative`, and the core `hidden` and `duplicate`. Copy `jevbrief/adapters/web/rules.py` as the pattern.
- **Benchmark:** the AndroidWorld or Android in the Wild datasets, where the correct next tap is known. The raw arm sends the full element list.

## 4. `vulns`: which security alert to fix first

- **Input:** scanner output (Dependabot alerts JSON, `trivy --format json`, or `grype -o json`), plus an optional SBOM (CycloneDX) and a lockfile.
- **Facts:** one per alert. Each carries severity (a word, not a CVSS number), whether the package is a direct or transitive dependency, whether it is dev-only, whether a fixed version exists, how old the alert is, and, where known, whether the code imports the package.
- **Rules:** `vulns.dev_only`, `vulns.no_fix`, `vulns.not_imported`, `vulns.duplicate_cve`, and boosts for known-exploited vulnerabilities (the CISA KEV list) and runtime dependencies.
- **Benchmark:** VEX-Bench. Check its license and format first.

## Definition of done, for every adapter

These are the steps each adapter so far has followed:

1. **Branch** off `main`: `feat/<name>-adapter`.
2. **Code:** `jevbrief/adapters/<name>/__init__.py`, standard library only where possible. Optional dependencies go in a `pyproject.toml` extra and are imported with `need(extra, module)`.
3. **Register it** in three places: `BUILTIN` in `jevbrief/adapters/__init__.py`, the entry point in `pyproject.toml`, and the CLI source help.
4. **Tests** in `tests/test_<name>.py`:
   - `check_adapter` passes
   - one test per reason code
   - one test per input format
   - `import jevbrief` still loads no adapter
5. **Benchmark:**
   - `bench/<name>/`, with a collector or generator, `tasks.json`, and `results.md`
   - real data when possible
   - an honest caveats section
   - labels written before the run and never changed afterwards
6. **Docs:**
   - `docs/adapters/<name>.md`, with the standard sections: at a glance, quick start, Python, input, what Jev sees, reason codes, options, question pack, benchmark, and limits
   - one row in the README's adapters table and one in its benchmarks table
   - rows in `docs/README.md` and `docs/concepts.md`
   - an entry in `PAGES` in `scripts/build_docs_site.py`
   - a row in `skills/jevbrief/SKILL.md`
7. **Release:**
   - bump the version in `jevbrief/__init__.py` (the only place it lives)
   - open a PR, merge it, then tag
   - `python -m build`, then list the package contents and confirm there are no `.env`, traces, or benchmark logs
   - upload with twine
   - rebuild the docs site and republish it to the same URL
   - write the GitHub release notes

## To start a new session

Paste this:

> Read `docs/roadmap-next.md` and `CLAUDE.md`. Build adapter #1 (`pr`) following the definition of done. Start with the parser and the reason codes, then the benchmark collector.
