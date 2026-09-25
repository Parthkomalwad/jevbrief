# mcp adapter benchmark

Run on 2026-09-25 with Jev, 40 tasks, 3 runs per task and arm.
- **Tools:** 105 real tools, collected with `fetch_tools.py` from four MCP servers: GitHub's official server (v1.12.2, 90 tools) and the reference time, fetch, and git servers (v1.30.0, 15 tools).
- **Tasks:** written by hand, 36 with a known right tool and 4 where no tool fits.

| Arm | Accuracy | Median input tokens | Median latency (ms) | Median confidence | Options |
|---|---|---|---|---|---|
| raw (every tool, full description) | 82% (98/120) | 13,450 | 415 | 0.94 | 105 |
| jevbrief (BM25 top 30) | **88% (105/120)** | **3,685** (−73%) | 356 | 0.93 | 30 |

## Where the arms differ

- **jevbrief right, raw wrong (6 tasks):**
  - opening a pull request (raw chose `git_status`)
  - approving a pull request (raw: `pull_request_read`)
  - reading a CI run's failing job logs (raw: `actions_list`)
  - re-running a workflow (raw: `actions_list`)
  - booking a restaurant, where no tool fits (raw: `fetch`)
  - one of three runs of "What is the capital of Australia?", where no tool fits

  With 105 options, Jev drifted toward general "read" and "list" tools.
- **raw right, jevbrief wrong (3 tasks):** "open a bug report" (`issue_write`), "show me the README" (`get_file_contents`), and "the newest published version" (`get_latest_release`). In all three, the ranking dropped the right tool because the goal shares no word with it (bug report and issue, README and file contents, version and release). This is the known limit of keyword ranking.
- **Both wrong (2 tasks):**
  - "Merge pull request 88 once it's approved": both arms chose `pull_request_read`. Checking the approval first is a reasonable next step, and the task's wording invites it; the label was kept as written.
  - "Push a fix to docs/setup.md directly on GitHub": `create_or_update_file` was in jevbrief's top 30, but Jev chose a different tool in each run.

## Ranking recall

Before asking Jev, the right tool survived the ranking for 33 of 36 goals (92%). Recall is measured with no Jev call:

```python
b = Briefing(McpAdapter(), goal, jev=FakeJev())
b.extract("bench/mcp/tools")
kept = [f.label for f in b.kept]
```

## Caveats

- **The tasks were written by hand**, by the same person who wrote the adapter. They were written before the ranking was run on them, and nothing was tuned after, but they are not an independent benchmark.
- **The ranking changed once, before the tasks were written:** URLs became the word `url`, and a short list of generic abbreviations was expanded (PR, repo, dir, config, msg, db). The three vocabulary misses above were not patched.
- **Real agents often see several hundred tools.** Add Docker servers (filesystem, memory, puppeteer, slack) with `fetch_tools.py` for a harder set.
