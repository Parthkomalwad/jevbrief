# otel adapter

Finds the log group that most likely explains an incident, from OpenTelemetry logs. Reads an OTLP JSON export (`{"resourceLogs": [...]}`) or a JSON Lines file of them, which is what the OpenTelemetry Collector's [`file` exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/fileexporter) writes. Standard library only.

```bash
jevbrief inspect logs.json --adapter otel --goal "Checkout requests started failing with 500 errors"
jevbrief ask     logs.json --adapter otel --goal "Checkout requests started failing with 500 errors" --view
```

```python
from jevbrief import Briefing
from jevbrief.adapters.otel import OtelAdapter

brief = Briefing(OtelAdapter(), goal="Checkout requests started failing with 500 errors", trace="traces/incident.jsonl")
brief.extract("logs.json")
decision = brief.decide()
if decision.fact:
    print("likely cause:", decision.fact.label, decision.fact.attrs)
```

## What Jev sees

Thousands of records become a handful of **log groups**. Records are grouped by service, severity, and message template: IDs, emails, IP addresses, and numbers become `<id>`, `<email>`, `<ip>`, and `<n>`, while 3-digit status codes such as `503` are kept.

Each group is sent with values computed in code, because Jev is weak at counting and comparing timestamps:

| Attribute | Values |
|---|---|
| `service`, `severity` | From the resource and severity number |
| `frequency` | `once`, `a few times`, `often`, `very often` |
| `first_seen` | `before the incident`, `at the incident start`, `after the incident started` |
| `still_happening` | `yes` or `no` (seen in the last minute of the export) |
| `exception.type`, `http.route`, `http.response.status_code`, `db.system`, `rpc.method`, `peer.service` | The most common value in the group, when present |

**Incident start:** the first error from a group that was not already erroring at the start of the export, so a background error that has been failing for hours does not count as the start. Set it yourself with `incident_start`.

## Rules

| Rule | Effect |
|---|---|
| `otel.below_severity` | Drops groups less severe than `min_severity` (default `warn`) |
| `otel.healthcheck` | Drops health checks, readiness and liveness probes, pings, and heartbeats |
| `otel.outside_window` | Drops groups with no records in `window` |
| `goal_match`, `otel.goal_match_attrs` | +0.35 when the message, service, route, or exception type shares a word with the goal |
| `otel.error` | +0.15 for error and fatal groups |
| `otel.early` | +0.15 for groups first seen at the incident start |
| Core | `unlabeled`, `duplicate`, `low_score`, `budget` |

## Options

Pass a config file with `--config otel.toml`, a dict to `OtelAdapter({...})`, or keyword arguments to `extract()`.

```toml
min_severity = "warn"                               # or "error", "info", or a severity number
incident_start = "2026-09-24T14:08:00Z"             # default: detected
window = ["2026-09-24T14:00:00Z", "2026-09-24T14:30:00Z"]
healthcheck = "/health\w*|heartbeat|/ping\b"      # regular expression
send_attributes = ["exception.type", "http.route", "k8s.pod.name"]
```

## Question pack

`likely_cause`: a Choice over the kept log groups plus "None of these log groups explains the incident", asking which group shows the cause rather than a symptom.

## Viewer

The `timeline` renderer draws one bar per log group from its first to its last record, marks the incident start, and animates with the replay.

## Benchmark

[bench/otel/results.md](../../bench/otel/results.md): 6 incidents, 3 runs each. Raw (the 254 most recent lines) 83% (15/18) at a median of 29,678 input tokens; jevbrief 100% (18/18) at 1,070 (96% fewer). Synthetic data; see the caveats.
