# ci adapter

Finds the error that most likely broke a CI build, and says whether the failure looks flaky. Standard library only.

| | |
|---|---|
| **Reads** | GitHub Actions log archives, `gh run view --log` output, plain logs, and JUnit XML |
| **Jev answers** | Which error broke the build, and whether the failure looks flaky |
| **Install** | `pip install jevbrief`. Standard library only. |
| **Main API** | `Briefing(CiAdapter(), goal)` and `--adapter ci` |
| **Benchmark** | 16 real failed runs: 100% against 88% on the cause, with 97% fewer tokens |

## Quick start

```bash
gh run view 123456 --log-failed > run.log
jevbrief inspect run.log --adapter ci --goal "CI is red on main"
jevbrief ask     run.log --adapter ci --goal "CI is red on main" --view
```

## Python

```python
from jevbrief import Briefing
from jevbrief.adapters.ci import CiAdapter

brief = Briefing(CiAdapter(), goal="CI is red on main", trace="traces/ci.jsonl")
brief.extract(["logs.zip", "reports/junit.xml"])
decision = brief.decide()
if decision.fact:
    print("likely cause:", decision.fact.label, decision.fact.attrs)
print("looks flaky:", decision.answers["flaky"]["noul"] > 0.5)
```

## Input

It reads any mix of:
- the log archive of a GitHub Actions run ("Download log archive", or `GET /repos/{owner}/{repo}/actions/runs/{id}/logs`), zipped or unzipped
- `gh run view <id> --log` or `--log-failed` output
- plain log files (the file name becomes the job name)
- JUnit XML reports (pytest `--junitxml`, Maven Surefire, Jest, gotestsum, ...)

Pass a file, a zip, a directory, or a list of paths.

## What Jev sees

A run's log becomes a few **failures**. Error lines are grouped by job, step, and message template (IDs, addresses, and numbers become placeholders, as in the otel adapter). Each failed JUnit test is one failure.

- **Steps:** GitHub's archives now hold one log per job. Steps are found from the `##[group]Run ...` markers GitHub writes at the start of each step.
- **Failing step:** the step with GitHub's `##[error]` marker.

| Attribute | Values |
|---|---|
| `job`, `step` | Where the lines came from |
| `severity` | `error` or `warning` |
| `frequency` | `once`, `a few times`, `often`, `very often` |
| `where` | `in the failing step`, `before the failing step`, `after the failing step`, or `unknown` |
| `looks_flaky` | `yes` when the text shows timeouts, connection or DNS errors, TLS resets, rate limits, 502 to 504 responses, a lost runner, a full disk, or out of memory, or when the test passed on a rerun |
| `test`, `error_type`, `result` | For failed JUnit tests |

Not counted as errors, even when they contain the word:
- source lines and local variables printed in tracebacks
- `Traceback (most recent call last)` headers and "During handling of the above exception" lines
- every line of a pytest `E` block after the first, since the block is one error
- lines like `0 errors`, `error_handler`, or `continue-on-error`

## Reason codes

| Rule | Effect |
|---|---|
| `ci.below_severity` | Drops warnings (default `min_severity = "error"`) |
| `ci.summary_line` | Drops exit-code lines, test-count summaries, and `====`, `____`, or `⎯⎯⎯⎯` banners |
| `ci.passed_step` | Drops error-looking output from steps before the failing step, which passed |
| `ci.after_failure` | Drops output from steps after the failing step, such as cleanup and cache saves |
| `ci.passed_on_rerun` | Drops JUnit tests that failed and then passed on a rerun |
| `goal_match` | +0.35 when the text shares a word with the goal |
| `ci.test_failure` | +0.15 for failed JUnit tests |
| `ci.first_error` | +0.1 for the first error in the failing step |
| `ci.failed_step` | +0.15 for output from the failing step |
| Core | `unlabeled`, `duplicate`, `low_score`, `budget` |

## Options

Pass a dict to `CiAdapter({...})` or keyword arguments to `extract()`.

```python
CiAdapter({"min_severity": "warning"})   # keep warnings too
```

## Question pack

`likely_cause` asks two questions in one call:
- a Choice over the kept failures, plus "None of these explains the build failure", asking which one shows the root cause rather than a symptom or follow-on error
- `flaky`, a Noul asking whether the failure comes from timing, the network, or the CI machine rather than a code change. Read it from `decision.answers["flaky"]["noul"]`, a probability from 0 to 1.

## Benchmark

[bench/ci/results.md](../../bench/ci/results.md): 16 real failed GitHub Actions runs from 7 public repos, 3 runs each, labeled by hand.

| Arm | Cause accuracy | Flaky accuracy | Median input tokens |
|---|---|---|---|
| raw (last 254 lines) | 88% | 93% | 30,502 |
| jevbrief | 100% | 67% | 988 |

The raw arm answered "flaky" for every run, which scores well because 13 of 16 labels are flaky. See the notes in the results file.

To rebuild the set:
1. Set `GITHUB_TOKEN`.
2. Run `python bench/ci/fetch_runs.py`.
3. Review the labels in `bench/ci/tasks.json`.

The logs are not committed, because GitHub deletes them after about 90 days.

## Limits

- **Flaky is the weaker answer.** On the benchmark, jevbrief scored 67% on it, against 93% for sending the raw log. The raw arm said "flaky" every time, and 13 of the 16 labels were flaky.
- **GitHub Actions only.** Steps are found from GitHub's `##[group]` and `##[error]` markers. Other CI systems still work as plain logs, but without step names or a failing step.
- **Error detection is pattern-based.** It is tuned on Python and JavaScript test output. Unusual tools may need `min_severity = "warning"`.
