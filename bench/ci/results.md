# ci adapter benchmark

Run on 2026-09-25 with Jev, 16 real failed GitHub Actions runs from public repos (flask, requests, pydantic, pytest, next.js, vite, prettier), collected by `fetch_runs.py`, 3 runs per task and arm. Only the failed jobs' logs are kept.

| Arm | Cause accuracy | Flaky accuracy | Median input tokens | Median latency (ms) | Median confidence | Median options |
|---|---|---|---|---|---|---|
| raw | 88% (42/48), 6 errors | 93% (39/42) | 30502 | 498 | 0.73 | 254 |
| jevbrief | 100% (48/48) | 67% (32/48) | 988 | 311 | 0.66 | 2 |

## Notes

- **Real data, hand-labeled.** The failures are real. The labels are not automatic: each task was labeled by reading the log and the commits that came next. `tasks.json` keeps a `note` with the reason for each label, and the links to the run and the fix, so every label can be checked.
- **Most "fixes" were flakes.** The collector looks for a failed run followed within 3 commits by a passing run of the same workflow. In 9 of 12 such cases the commits in between did not touch anything related to the error, so the failure was most likely a flake (network, TLS, timing). Only 3 of 16 tasks are real code failures. Labels of the form "flaky because the next commit was unrelated" are a judgment, not proof.
- **Cause:** jevbrief kept the right error group in all 16 runs and Jev picked it every time, with 31 times fewer input tokens. The raw arm (the last 254 log lines) failed on two runs because the log was over Jev's context limit (the 6 errors).
- **Flaky: raw scores higher, but mostly by always saying yes.** The raw arm answered "flaky" (0.57 to 0.81) for every task, including the real vite worker crash, which scores well because 13 of 16 labels are flaky. jevbrief answered with more spread (0.08 for the flask deprecation, 0.10 for the pytest Cython warning, 0.87 for the pydantic font download), but called four vite and prettier timing failures real. These are the least certain labels. The flaky rules were not tuned to this set.
- **Small set.** 16 runs from the last 100 runs of each repo. A larger, more balanced set (more real code failures) is the next step.
