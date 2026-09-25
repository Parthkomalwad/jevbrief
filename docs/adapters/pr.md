# pr adapter

Finds the chunk of a pull request that most needs a human reviewer, and asks whether the PR looks safe to merge. Standard library only.

| | |
|---|---|
| **Reads** | `gh pr diff` output, `.diff` and `.patch` files, and the GitHub API's `/pulls/{n}/files` JSON |
| **Jev answers** | Which chunk most needs a human reviewer, and whether the PR is safe to merge without changes |
| **Install** | `pip install jevbrief`. Standard library only. |
| **Main API** | `Briefing(PrAdapter(), goal)` and `--adapter pr` |
| **Benchmark** | 37 real merged PRs: 55% against 55% on the chunk, with 36% fewer tokens |

## Quick start

```bash
gh pr diff 123 > pr.diff
jevbrief inspect pr.diff --adapter pr --goal "Add refunds for token holders"
jevbrief ask     pr.diff --adapter pr --goal "Add refunds for token holders" --view
```

Use the PR's title, or what it is meant to do, as the goal.

## Python

```python
from jevbrief import Briefing
from jevbrief.adapters.pr import PrAdapter

brief = Briefing(PrAdapter(), goal="Add refunds for token holders", trace="traces/pr.jsonl")
brief.extract("pr.diff")
decision = brief.decide()
if decision.fact:
    print("review first:", decision.fact.label, decision.fact.attrs)
print("safe to merge:", decision.answers["safe_to_merge"]["noul"] > 0.5)
```

## Input

It reads any mix of:
- a unified diff: `gh pr diff <n>`, `git diff`, or a `.diff` file
- a `git format-patch` or GitHub `.patch` file. The mail headers and commit message are skipped.
- the GitHub API's `/pulls/{n}/files` JSON, where each file holds its own `patch`. Add `/pulls/{n}` as another JSON file to use the PR's title and number.
- a folder holding any of these

Pass a file, a folder, a list of paths, or the diff text itself.

## What Jev sees

Each diff chunk (hunk) is one fact. A renamed or binary file with no chunks is one fact for the file. Everything below is computed in code and sent as words.

| Attribute | Values |
|---|---|
| `file`, `lines`, `in` | Where the chunk is: the path, the new line range, and the function or class from the hunk header |
| `role` | `source`, `test`, `config`, `docs`, `generated`, `lockfile`, or `vendored`, from the path and the file's first lines |
| `size` | `small` (up to 5 changed lines), `medium` (up to 30), or `large` |
| `change` | `added`, `removed`, or `modified` |
| `matching_test_changed` | For source files: `yes` when the PR also changes a test with the same name, such as `test_fees.py` or `fees.spec.ts` for `fees.py` |
| `touches` | Any of `public API`, `auth or security`, `SQL`, `concurrency`, `error handling`, found from keywords in the changed lines |
| `excerpt` | The first 160 characters of the changed lines |
| `renamed_from` | The old path, for moved files |

## Reason codes

| Rule | Effect |
|---|---|
| `pr.generated` | Drops lockfiles (`package-lock.json`, `poetry.lock`, `go.sum`, ...) and generated files (`*.min.js`, `*_pb2.py`, `*.pb.go`, snapshots, or files marked `@generated` or `DO NOT EDIT`) |
| `pr.vendored` | Drops files under `vendor/`, `third_party/`, `node_modules/`, and similar folders |
| `pr.rename_only` | Drops files that were renamed or moved with no other change |
| `pr.formatting_only` | Drops chunks where only whitespace or line breaks changed |
| `pr.docs_only` | Drops documentation chunks, only when `drop_docs` is set |
| `goal_match` | +0.35 when the text shares a word with the goal |
| `pr.risky_area` | +0.2 for chunks that touch auth or security, SQL, concurrency, or a public API |
| `pr.no_test` | +0.1 for source chunks with no matching test change |
| Core | `unlabeled`, `duplicate`, `low_score`, `budget` |

## Options

Pass a dict to `PrAdapter({...})`.

```python
PrAdapter({"drop_docs": True})   # skip documentation chunks
```

## Question pack

`needs_review` asks two questions in one call:
- a Choice over the kept chunks, plus "None of these needs careful review", asking which one is most likely to hide a bug, a security problem, or a design issue
- `safe_to_merge`, a Noul asking whether the PR is safe to merge without changes. Read it from `decision.answers["safe_to_merge"]["noul"]`, a probability from 0 to 1.

## Benchmark

[bench/pr/results.md](../../bench/pr/results.md): 37 real merged pull requests from 14 public repos, 3 runs each. A pick is right when it names a chunk that got a review comment from someone other than the author, on the commit the first review saw.

| Arm | Accuracy | Median input tokens |
|---|---|---|
| random chunk (free) | 26% | – |
| largest chunk (free) | 49% | – |
| raw (the full diff) | 55% | 2,599 |
| jevbrief | 55% | 1,652 |

jevbrief matched the full diff with 36% fewer tokens. It did not pick better. Most PRs in the set are small (a median of 6 chunks), so the savings are small too.

To rebuild the set:
1. Set `GITHUB_TOKEN`.
2. Run `python bench/pr/fetch_prs.py`.
3. Review the labels in `bench/pr/tasks.json` before any run.

The diffs are not committed.

## Limits

- **No better than the full diff on accuracy.** On the benchmark, both arms scored 55%, only 6 points above picking the largest chunk.
- **Review comments are a weak truth.** A comment shows where a reviewer looked, not always the riskiest chunk. Typos and naming get comments too.
- **`touches` is keyword-based.** A chunk that mentions `token` or `session` counts as auth even when it is not. It reads changed lines only, not the code around them.
- **The budget can cut the right chunk.** About 20 chunks are kept. On very large PRs, a chunk that needs review can be dropped.
- **`safe_to_merge` is not measured.** The benchmark has no PRs that should not have been merged.
