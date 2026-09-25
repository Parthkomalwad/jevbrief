# Command line

The CLI reads `TYPESAFE_API_KEY` from the environment, or from a `.env` file in the current folder. Only `ask` and `bench` call Jev.

## `jevbrief inspect`

Shows which facts would be kept and dropped, with the reason for each. It makes no Jev call and needs no API key.

```bash
jevbrief inspect <source> --adapter <name> --goal "<goal>" [--config FILE] [--pack NAME] [--budget 2000]
```

| Argument | Meaning |
|---|---|
| `source` | What to brief. It depends on the adapter: a URL or HTML file (web), a JSON file (json), an OTLP export (otel), a log, zip, or folder (ci), or a tools JSON file or folder (tools) |
| `--adapter` | The adapter name (default `web`). See `jevbrief adapters` |
| `--goal` | What the agent is trying to do |
| `--config` | An adapter config file. Required by json |
| `--pack` | The question pack (default: the adapter's first) |
| `--budget` | The token budget for the state (default 2000) |

## `jevbrief ask`

Asks Jev the adapter's question and writes a trace. It takes every `inspect` argument, plus:

| Argument | Meaning |
|---|---|
| `--trace` | Trace file (default `traces/trace.jsonl`) |
| `--trace-level` | `off`, `summary` (default), or `full`. `full` also stores the questions and the state sent to Jev |
| `--min-confidence` | Below this, the outcome is `low_confidence` and no action is taken (default 0.5) |
| `--view` | Open the viewer when done |
| `--no-screenshot` | Do not store an image in the trace (web) |

## `jevbrief view`

Opens a trace in the viewer. The viewer is one HTML file with everything embedded, and it works offline.

```bash
jevbrief view [trace.jsonl] [--no-open] [--live] [--port 8765]
```

With no file, it opens the newest trace in `traces/`. `--live` serves the viewer on `127.0.0.1` and shows new decisions as they are written.

## `jevbrief bench`

Runs a benchmark: the raw arm against jevbrief, on a tasks file.

```bash
jevbrief bench bench/mcp/tasks.json [--repeats 3] [--out traces/bench]
```

Each task has an `adapter`, a `source` (relative to the tasks file), a `goal`, and one expected answer. The expected answer is one of:
- `expected_label`: a label or a list of labels
- `expected_contains`: a string or a list of strings
- `expected_choice`: for example `"none"`
- `flaky`: `true` or `false`, scored on the pack's `flaky` question

Tasks with no expected answer are skipped.

## `jevbrief adapters`

Lists the installed adapters: the built-in ones, and any installed package that registers a `jevbrief.adapters` entry point.
