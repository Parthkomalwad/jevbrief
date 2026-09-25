# otel adapter

Finds the signal that most likely explains an incident: a group of log messages, a group of Kubernetes events, or an alert, all on one timeline. Standard library only.

| | |
|---|---|
| **Reads** | OpenTelemetry logs (OTLP JSON), Kubernetes events (`kubectl get events -o json`), and Alertmanager or Prometheus alerts |
| **Jev answers** | Which signal most likely shows the cause of an incident, rather than a symptom |
| **Install** | `pip install jevbrief`. Standard library only. |
| **Main API** | `Briefing(OtelAdapter(), goal)` and `--adapter otel` |
| **Benchmark** | Logs only: 6 synthetic incidents, 100% against 83%, with 96% fewer tokens. Logs, events, and alerts: 8 synthetic incidents, 100% against 71%, with 94% fewer tokens |

## Quick start

Logs alone:

```bash
jevbrief inspect logs.json --adapter otel --goal "Checkout requests started failing with 500 errors"
jevbrief ask     logs.json --adapter otel --goal "Checkout requests started failing with 500 errors" --view
```

Logs, Kubernetes events, and alerts together, from one folder:

```bash
mkdir incident
cp logs.json incident/
kubectl get events -A -o json > incident/events.json
curl -s http://alertmanager:9093/api/v2/alerts > incident/alerts.json
jevbrief ask incident --adapter otel --goal "Checkout keeps failing with 503 errors" --view
```

## Python

```python
from jevbrief import Briefing
from jevbrief.adapters.otel import OtelAdapter

brief = Briefing(OtelAdapter(), goal="Checkout keeps failing with 503 errors", trace="traces/incident.jsonl")
brief.extract(["logs.json", "events.json", "alerts.json"])   # or one file, a folder, or parsed JSON
decision = brief.decide()
if decision.fact:
    print("likely cause:", decision.fact.kind, decision.fact.label, decision.fact.attrs)
```

## Input

It reads any mix of:
- **OpenTelemetry logs:** an OTLP JSON export (`{"resourceLogs": [...]}`) or JSON Lines of them, which is what the OpenTelemetry Collector's [`file` exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/fileexporter) writes
- **Kubernetes events:** `kubectl get events -A -o json`, in the core `v1` or the `events.k8s.io` format
- **Alerts:** Alertmanager's `/api/v2/alerts`, an Alertmanager webhook payload, or Prometheus's `/api/v1/alerts`

Pass a file, a folder, a list of paths, or the parsed JSON. Each file's kind is detected from its content.

## What Jev sees

Thousands of records become a handful of **signals**, each sent with values computed in code, because Jev is weak at counting and comparing timestamps.

- **Log groups:** records grouped by service, severity, and message template. IDs, emails, IP addresses, and numbers become `<id>`, `<email>`, `<ip>`, and `<n>`, while 3-digit status codes such as `503` are kept.
- **Kubernetes event groups:** events grouped by reason, object, and message, such as `BackOff Pod checkout`. Pod names lose their generated suffix (`checkout-7d9f8b6c4-x2k9q` becomes `checkout`), and an event's own repeat `count` feeds `frequency`.
- **Alerts:** one per alert name and service.

| Attribute | Values |
|---|---|
| `service`, `severity` | From the resource, the severity number, the event type, or the alert's `severity` label |
| `frequency` | `once`, `a few times`, `often`, `very often` |
| `first_seen` | `before the incident`, `at the incident start`, `after the incident started` |
| `still_happening` | `yes` or `no`: seen in the last minute of the export, or, for alerts, still firing |
| `source` | `Kubernetes event` or `alert`. Log groups have none. |
| `reason`, `object` | For events: the event reason and the object kind and name |
| `alert`, `state`, `firing_for` or `fired_for` | For alerts: the name, `firing`, `pending`, or `resolved`, and how long it fired, in words |
| `exception.type`, `http.route`, `http.response.status_code`, `db.system`, `rpc.method`, `peer.service` | For logs: the most common value in the group, when present |

**Incident start:** the first error log or Warning event from a group that was not already failing at the start of the export, so a background error that has been failing for hours does not count as the start. Alerts are left out, because they fire after the cause. Set it yourself with `incident_start`.

With logs alone, Jev gets exactly the same state and question as before events and alerts were added.

## Reason codes

| Rule | Effect |
|---|---|
| `otel.routine_event` | Drops routine Kubernetes events: Scheduled, Pulling, Pulled, Created, Started, SuccessfulCreate, ScalingReplicaSet, and similar |
| `otel.resolved_alert` | Drops alerts that fired and resolved before the incident started. An alert that resolved during the incident is kept. |
| `otel.below_severity` | Drops signals less severe than `min_severity` (default `warn`), including Normal events |
| `otel.healthcheck` | Drops log health checks, probes, pings, and heartbeats. A failed Kubernetes probe event is kept, since it is often the signal. |
| `otel.outside_window` | Drops signals with no records in `window` |
| `goal_match`, `otel.goal_match_attrs` | +0.35 when the message, service, route, exception type, event reason, or alert name shares a word with the goal |
| `otel.error` | +0.15 for error and fatal signals |
| `otel.early` | +0.15 for signals first seen at the incident start |
| Core | `unlabeled`, `duplicate`, `low_score`, `budget` |

## Options

Pass a config file with `--config otel.toml`, a dict to `OtelAdapter({...})`, or keyword arguments to `extract()`.

```toml
min_severity = "warn"                               # or "error", "info", or a severity number
incident_start = "2026-09-24T14:08:00Z"             # default: detected
window = ["2026-09-24T14:00:00Z", "2026-09-24T14:30:00Z"]
healthcheck = "/health\w*|heartbeat|/ping\b"      # regular expression, for logs
send_attributes = ["exception.type", "http.route", "k8s.pod.name"]
```

## Question pack

`likely_cause`: a Choice over the kept signals plus "None of these explains the incident", asking which one shows the cause rather than a symptom. With logs alone it asks about `log_groups`; with events or alerts it asks about `signals`.

## Viewer

The `timeline` renderer draws one bar per signal from its first to its last record, marks the incident start, and animates with the replay. Kubernetes events are tagged `k8s` and alerts `alert`.

## Benchmark

Two synthetic sets, 3 runs per task:

| Set | Arm | Accuracy | Median input tokens |
|---|---|---|---|
| [Logs only](../../bench/otel/results.md): 6 incidents | raw (the 254 most recent lines) | 83% | 29,678 |
| | jevbrief | 100% | 1,070 |
| [Logs, events, and alerts](../../bench/incident/results.md): 8 incidents | raw (every event and alert, then the latest lines) | 71% | 29,912 |
| | jevbrief | 100% | 1,830 |

In the second set, the cause is in Kubernetes events for 5 incidents, in an alert for 1, and in the logs for 2, where loud alerts are only symptoms. The raw arm's misses were a background "slow query" warning chosen over the cause, and a single cause line that had scrolled out of the latest logs.

## Limits

- **Synthetic benchmarks.** Both sets were written while building the adapter, by the same person who wrote the rules, so treat the numbers as an illustration. Real, anonymized incident exports are welcome.
- **An alert-only cause can look early.** Alerts do not set the incident start. When the only cause signal is an alert, the start comes from the first symptom, and the cause alert can read as `before the incident`. It is still sent to Jev.
- **Traces and metrics are not read.** Only logs, Kubernetes events, and alerts.
- **Event grouping uses the object name.** Two pods of the same app share a group. Two different apps with the same name in different namespaces also share one.
