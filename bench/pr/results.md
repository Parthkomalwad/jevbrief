# pr adapter benchmark

Run on 2026-09-25 with Jev, 37 real merged pull requests from 14 public repos (requests, httpx, pydantic, fastapi, pytest, poetry, django, vite, prettier, express, cli, uv, and others), collected by `fetch_prs.py`, 3 runs per task and arm.

**Question:** which chunk of the diff most needs a human reviewer? **Right answer:** any chunk that got a review comment from someone other than the author, on the commit the first review round saw.

| Arm | Accuracy | Median input tokens | Median latency (ms) | Median confidence | Median options |
|---|---|---|---|---|---|
| raw | 55% (61/111) | 2599 | 331 | 0.83 | 6 |
| jevbrief | 55% (61/111) | 1652 | 322 | 0.78 | 6 |

Free baselines on the same 37 PRs (no model call):

| Baseline | Accuracy |
|---|---|
| random chunk | 26% (expected) |
| the chunk the rules score highest | 41% (15/37) |
| the largest chunk (most changed lines) | 49% (18/37) |

## Notes

- **A tie on accuracy.** Both arms picked a commented chunk 55% of the time. jevbrief used 36% fewer input tokens at the median. It did not make Jev better at this question, it made the same answer cheaper. The two arms disagree on 8 PRs: jevbrief did better on 4 (django #21138, prettier #20100, requests #7431, httpx #2252) and raw on 4 (express #7459, pytest #14984, prettier #20060, cli #14282).
- **Jev beats the free baselines, but not by much.** 55% against 49% for "pick the largest chunk". Most of the signal is size.
- **The savings are small because the PRs are small.** The median PR has 6 chunks and a raw diff of about 2,600 tokens. Savings on large PRs (40 or more chunks) were not measured separately; there are only three in this set.
- **The labels are a weak truth.** A review comment means a reviewer looked closely at a chunk, not that it was the chunk that most needed review. Reviewers comment on typos, naming, and docs (4 of 37 PRs have only nit or suggestion comments, and 5 are mostly documentation). A chunk with no comment may have been reviewed carefully and found fine. So 55% is a floor on usefulness, not a measure of it.
- **Hand-reviewed labels, frozen before the run.** The collector labeled 40 PRs automatically. Before any run, 3 were dropped (comments that were not reviews of the code: "fixed on main already", an aside about a token, "I don't have time to review this properly"), and one PR's chunks commented only by an AI review bot were removed. `tasks.json` records the reason in `review` for each task, with the comments and links. Labels were committed (b879520) before the run and not changed after.
- **The budget can drop the right chunk.** jevbrief keeps about 20 chunks. In uv #21908 (70 chunks), every commented chunk was cut, so jevbrief could not be right. In 36 of 37 PRs at least one commented chunk was kept.
- **Not scored: safe to merge.** Every PR here was merged after review comments, so there is no ground truth for the `safe_to_merge` Noul.
- **Small set.** 37 PRs, the most recently updated merged PRs with review comments in each repo. The diffs are not committed; `fetch_prs.py` collects them again.

## Per task

| Task | raw | jevbrief |
|---|---|---|
| psf_requests_6951: docs: fix dead links to kenreitz.org | 0/3 | 0/3 |
| encode_httpx_307: Added support ssl cert file environment | 0/3 | 0/3 |
| encode_httpx_3419: Version 0.28.0. | 0/3 | 0/3 |
| pydantic_pydantic_12050: Migrate branding | 0/3 | 0/3 |
| pydantic_pydantic_9459: Add pipeline API | 3/3 | 3/3 |
| pytest-dev_pytest_15011: Clarify the relation between marks and k | 0/3 | 0/3 |
| pytest-dev_pytest_15044: Warn when writing or closing a cache fil | 3/3 | 3/3 |
| python-poetry_poetry_10975: fix(init): sanitize default package name | 3/3 | 3/3 |
| python-poetry_poetry_11042: Reduce virtual environment discovery sub | 3/3 | 3/3 |
| django_django_21975: Fixed #37344 -- Enabled FETCH_PEERS batc | 0/3 | 0/3 |
| django_django_21138: Fixed #37051 -- Improved organisation of | 0/3 | 3/3 |
| vitejs_vite_23568: fix(bundled-dev): serve the rolldown run | 3/3 | 3/3 |
| vitejs_vite_18190: feat: introduce RunnableDevEnvironment | 0/3 | 0/3 |
| prettier_prettier_20066: Preserve Angular control flow syntax in  | 3/3 | 3/3 |
| prettier_prettier_20100: Move "dependents count update" out of re | 0/3 | 3/3 |
| expressjs_express_7459: fix(res.send): preserve ETag generation  | 3/3 | 0/3 |
| expressjs_express_5555: fix #5554 passing URL instances with new | 3/3 | 3/3 |
| cli_cli_14356: Run acceptance tests in Actions with a G | 3/3 | 3/3 |
| cli_cli_14282: Propagate gh path to extensions | 3/3 | 2/3 |
| astral-sh_uv_21942: Unify generation of sdists with "malicio | 3/3 | 3/3 |
| psf_requests_7431: Fix mutability issues with headers input | 0/3 | 2/3 |
| encode_httpx_3552: Add httpx-retries to third party package | 0/3 | 0/3 |
| encode_httpx_2252: Drop `rfc3986` requirement. | 2/3 | 3/3 |
| fastapi_fastapi_16049: ⚡️ Reduce memory usage in dependencies | 3/3 | 3/3 |
| pytest-dev_pytest_14989: fix: bytecode cache invalidation for mov | 0/3 | 0/3 |
| pytest-dev_pytest_14984: fixtures: use a better data structure fo | 2/3 | 0/3 |
| python-poetry_poetry_11037: Fix sdist extraction on older Python ver | 3/3 | 3/3 |
| python-poetry_poetry_10982: Fix explicit-priority sources not checke | 3/3 | 3/3 |
| django_django_21956: Fixed #37339 -- Allowed ipaddress object | 3/3 | 3/3 |
| django_django_21597: Fixed #37136 --  Integrate Oracle Test P | 3/3 | 3/3 |
| vitejs_vite_23437: fix: only treat whole `node_modules` pat | 3/3 | 3/3 |
| vitejs_vite_23333: feat(devtools): enable dev server integr | 0/3 | 0/3 |
| prettier_prettier_20015: Angular: Support `@boundary` / `@error`  | 0/3 | 0/3 |
| prettier_prettier_20060: [MDX] improve attribute formatting | 3/3 | 0/3 |
| cli_cli_14313: Validate repository names during interac | 3/3 | 3/3 |
| astral-sh_uv_21908: Remove redundant test snapshot filters | 0/3 | 0/3 |
| astral-sh_uv_21880: Check nonisolated build dependencies in  | 0/3 | 0/3 |
