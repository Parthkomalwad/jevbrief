# Threads, processes, and async

jevbrief is safe to use from many threads, many processes, and async code, with a few simple rules. Each rule below is covered by a test in `tests/test_concurrency.py`, which also runs on free-threaded Python (no GIL) in CI.

## The rules

| What | Share it? |
|---|---|
| An adapter (`get_adapter("otel")`, `CiAdapter()`, ...) | **Yes**, across threads. Adapters keep no state between calls |
| A `Jev` client | **Yes**, across threads and event loops. Its async client is created per event loop |
| A `Briefing` (or a web `Brief`) | **No.** It remembers its last answer and facts. Use one per thread, task, or agent |
| A trace file | **Yes.** Writes are locked, across threads and processes |
| A sync Playwright page | **No.** Keep it on the thread that created it, or use async Playwright |

## Threads

Share the adapter and the `Jev` client, and create a `Briefing` per call:

```python
from concurrent.futures import ThreadPoolExecutor
from jevbrief import Briefing, get_adapter
from jevbrief.jev import Jev

adapter = get_adapter("ci")
jev = Jev(timeout=15, retries=3)                 # one HTTP connection pool for every thread

def triage(log_path):
    brief = Briefing(adapter, "CI is red on main", jev=jev, trace="traces/ci.jsonl")
    brief.extract(log_path)
    return brief.decide()

with ThreadPoolExecutor(max_workers=8) as pool:
    decisions = list(pool.map(triage, log_paths))
```

`pick_tool`, `select_tools`, `check_progress`, and `loop_signals` are safe to call from many threads at once.

## Async

Use the `a` versions. They return the same results without blocking the event loop:

```python
decisions = await asyncio.gather(*(brief_for(src).adecide() for src in sources))
pick = await apick_tool(tools, goal)
progress = await acheck_progress(history, goal)
```

Many `adecide()` calls can share one `Jev`. Each event loop gets its own async client, so one `Jev` also works across several `asyncio.run` calls. Close it with `await jev.aclose()` in each loop you used, and `jev.close()` for the sync client.

## Processes

A `Briefing` cannot be sent to another process, because its rules are functions. Send what it is built from instead, and build it in the worker:

```python
from concurrent.futures import ProcessPoolExecutor
from jevbrief import Briefing, get_adapter

def triage(job):                                  # a top-level function, so workers can import it
    adapter_name, source, goal = job
    brief = Briefing(get_adapter(adapter_name), goal, trace=f"traces/{adapter_name}.jsonl")
    brief.extract(source)
    d = brief.decide()
    return d.outcome, d.choice, d.confidence       # plain values travel between processes

if __name__ == "__main__":                        # needed on Windows and macOS
    jobs = [("ci", path, "CI is red on main") for path in log_paths]
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(triage, jobs))
```

Facts, `Extracted`, `Decision`, and every built-in adapter can be pickled, so you can also extract in one process and decide in another.

Each process loads its own copy of anything it caches. With hybrid tool ranking, that is the embedding model: about 67 MB per process.

## Trace files

Many threads and processes can write to one trace file. Each record is written under a lock: a thread lock inside a process, and an operating-system lock on a small `<trace>.jsonl.lock` file next to the trace across processes. Readers, such as `jevbrief view --live`, are never blocked.

Before 0.8.1, parallel writers on Windows could lose records. One trace file per process or run is still the simplest layout, and the viewer opens any of them.

## Free-threaded Python

jevbrief runs on free-threaded Python (3.14t, without the GIL). CI runs the core and the standard-library adapters on it. The web adapter (Playwright) and hybrid tool ranking (fastembed) depend on packages that may not publish free-threaded builds yet.
