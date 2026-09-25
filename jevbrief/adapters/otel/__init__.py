"""The otel adapter: OpenTelemetry logs, Kubernetes events, and alerts to signal facts, for finding an incident's cause.

Reads any mix of (as parsed JSON, files, a folder, or a list of paths):
- OTLP JSON log exports (`{"resourceLogs": [...]}`) or JSON Lines of them, as written by the
  OpenTelemetry Collector's `file` exporter
- Kubernetes events: `kubectl get events -A -o json` (core/v1 or events.k8s.io)
- alerts: Alertmanager's `/api/v2/alerts`, an Alertmanager webhook payload, or Prometheus's `/api/v1/alerts`
Standard library only.

Records are grouped by service, severity, and message template (IDs, numbers, and addresses
replaced with placeholders). Counts, times, and ordering are computed here and sent to Jev as
words, because Jev is weak at counting and comparing timestamps.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ...briefing import Extracted
from ...facts import Fact, clean_label, fact_id, register_reasons
from ...questions import FactChoice
from ...rules import CORE_RULES, Boost, Drop, Rule, RuleSet
from .. import Adapter, need

BELOW_SEVERITY = "otel.below_severity"
HEALTHCHECK = "otel.healthcheck"
OUTSIDE_WINDOW = "otel.outside_window"
ROUTINE_EVENT = "otel.routine_event"
RESOLVED_ALERT = "otel.resolved_alert"
REASONS = {
    BELOW_SEVERITY: "Less severe than the minimum severity (default: warnings and above)",
    HEALTHCHECK: "Health check, readiness, or heartbeat noise",
    OUTSIDE_WINDOW: "No records inside the incident time window",
    ROUTINE_EVENT: "Routine Kubernetes event (Scheduled, Pulled, Created, Started, ...)",
    RESOLVED_ALERT: "Alert that had already resolved before the incident started",
    "otel.goal_match_attrs": "Kept: the service, route, or exception type shares a word with the goal",
    "otel.error": "Kept: error or fatal severity",
    "otel.early": "Kept: first seen at the incident start",
}

LEVELS = [(1, "trace"), (5, "debug"), (9, "info"), (13, "warn"), (17, "error"), (21, "fatal")]
TEXT_LEVELS = {"trace": 1, "debug": 5, "info": 9, "information": 9, "warn": 13, "warning": 13,
               "error": 17, "err": 17, "critical": 21, "fatal": 21}
SEND_ATTRIBUTES = ["exception.type", "http.route", "http.response.status_code", "http.status_code",
                   "db.system", "rpc.method", "peer.service"]
# Health check endpoints and heartbeats, but not errors that mention health ("no healthy upstream").
HEALTHCHECK_PATTERN = r"/health\w*|\bhealth ?checks?\b|/readyz?\b|/livez?\b|readiness probe|liveness probe|/ping\b|heartbeat|keep-?alive"
NEAR_S = 60  # "at the incident start" means within a minute of it
ROUTINE_REASONS = {"Scheduled", "Pulling", "Pulled", "Created", "Started", "SuccessfulCreate", "SuccessfulDelete",
                   "ScalingReplicaSet", "SuccessfulMountVolume", "SuccessfulAttachVolume", "NodeReady",
                   "RegisteredNode", "Starting", "LeaderElection", "Completed", "SawCompletedJob", "Sync",
                   "NodeHasSufficientMemory", "NodeHasNoDiskPressure", "NodeHasSufficientPID"}
ALERT_LEVELS = {"critical": 21, "page": 21, "high": 17, "error": 17, "major": 17, "warning": 13, "warn": 13,
                "minor": 13, "info": 9, "none": 9, "low": 9}
POD_SUFFIX = re.compile(r"-[a-f0-9]{8,10}-[a-z0-9]{5}$|-[a-z0-9]{5}$|-\d+$")  # checkout-7d9f8b6c4-x2k9q -> checkout


def _number(m: re.Match) -> str:
    # Bare 3-digit status codes (100-599) carry meaning ("503"), so they stay. Other numbers become <n>.
    return m.group(0) if re.fullmatch(r"[1-5]\d\d", m.group(0)) else "<n>"


_SUBS = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<id>"),
    (re.compile(r"\b[0-9a-f]{12,}\b", re.I), "<id>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "<email>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\d+(?:\.\d+)?(?:ms|s|m|h|%|kb|mb|gb)?\b", re.I), _number),
]


def template(body: str) -> str:
    """Replace IDs, emails, addresses, and numbers so repeated messages group together."""
    t = str(body)
    for pattern, repl in _SUBS:
        t = pattern.sub(repl, t)
    return " ".join(t.split())


def level_of(number: int) -> str:
    name = "unknown"
    for start, n in LEVELS:
        if number >= start:
            name = n
    return name


def _value(v: dict):
    """Convert an OTLP AnyValue to a Python value."""
    if not isinstance(v, dict):
        return v
    for key in ("stringValue", "boolValue", "doubleValue"):
        if key in v:
            return v[key]
    if "intValue" in v:
        return int(v["intValue"])
    if "arrayValue" in v:
        return [_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return {kv["key"]: _value(kv.get("value", {})) for kv in v["kvlistValue"].get("values", [])}
    return None


def _attrs(items) -> dict:
    return {kv["key"]: _value(kv.get("value", {})) for kv in items or []}


def records(data):
    """Yield flat log records from OTLP JSON: dicts with ts (ns), sev, body, service, attrs."""
    for export in data if isinstance(data, list) else [data]:
        for rl in export.get("resourceLogs", []):
            resource = _attrs(rl.get("resource", {}).get("attributes"))
            service = str(resource.get("service.name", "unknown"))
            for sl in rl.get("scopeLogs", rl.get("instrumentationLibraryLogs", [])):
                for r in sl.get("logRecords", []):
                    sev = int(r.get("severityNumber") or 0) or TEXT_LEVELS.get(str(r.get("severityText", "")).lower(), 9)
                    ts = int(r.get("timeUnixNano") or r.get("observedTimeUnixNano") or 0)
                    body = _value(r.get("body", {}))
                    yield {"ts": ts, "sev": sev, "body": "" if body is None else str(body), "service": service,
                           "attrs": _attrs(r.get("attributes")), "src": "log"}


def _ns_or(*isos) -> int:
    """The first usable time, in ns. Go's zero time (0001-01-01) means unset."""
    for t in isos:
        if t and not str(t).startswith("0001-"):
            return _ns(t)
    return 0


def k8s_events(data: dict):
    """Records from `kubectl get events -o json` (core/v1 or events.k8s.io)."""
    for e in data.get("items", []):
        obj = e.get("involvedObject") or e.get("regarding") or {}
        meta = e.get("metadata", {})
        series = e.get("series") or {}
        first = _ns_or(e.get("firstTimestamp"), e.get("eventTime"), meta.get("creationTimestamp"))
        last = _ns_or(e.get("lastTimestamp"), series.get("lastObservedTime")) or first
        name = obj.get("name", "")
        yield {"ts": first, "end": max(last, first), "src": "event",
               "n": int(e.get("count") or series.get("count") or e.get("deprecatedCount") or 1),
               "sev": 13 if e.get("type") == "Warning" else 9, "body": e.get("message") or e.get("note") or "",
               "service": (POD_SUFFIX.sub("", name) if obj.get("kind") == "Pod" else name) or "unknown",
               "attrs": {"reason": e.get("reason", ""), "object_kind": obj.get("kind", ""),
                         "namespace": obj.get("namespace", "")}}


def alerts(data):
    """Records from Alertmanager (API v2 or a webhook payload) or Prometheus `/api/v1/alerts`."""
    items = data if isinstance(data, list) else (data.get("data") or {}).get("alerts") or data.get("alerts") or []
    for a in items:
        labels, ann = a.get("labels", {}), a.get("annotations", {})
        status = a.get("status")
        state = (status.get("state") if isinstance(status, dict) else status) or a.get("state") or "firing"
        name = labels.get("alertname", "alert")
        summary = ann.get("summary") or ann.get("description") or ann.get("message") or ""
        yield {"ts": _ns_or(a.get("startsAt"), a.get("activeAt")), "alert_end": _ns_or(a.get("endsAt")), "src": "alert",
               "state": "resolved" if state == "resolved" else "pending" if state == "pending" else "firing",
               "sev": ALERT_LEVELS.get(str(labels.get("severity", "")).lower(), 13),
               "body": f"{name}: {summary}" if summary else name,
               "service": str(labels.get("service") or labels.get("job") or labels.get("app")
                              or labels.get("namespace") or "unknown"),
               "attrs": {"alertname": name, "severity_label": labels.get("severity", "")}}


def classify(data) -> str | None:
    """"logs", "events", "alerts", or None, for one parsed JSON document."""
    if isinstance(data, list):
        first = data[0] if data and isinstance(data[0], dict) else {}
        return "logs" if "resourceLogs" in first else "alerts" if "labels" in first else None
    if not isinstance(data, dict):
        return None
    if "resourceLogs" in data:
        return "logs"
    items = data.get("items")
    if isinstance(items, list) and (data.get("kind") in ("EventList", "List") or items) and (
            not items or "involvedObject" in items[0] or "regarding" in items[0]):
        return "events"
    if isinstance((data.get("data") or {}).get("alerts"), list) or isinstance(data.get("alerts"), list):
        return "alerts"
    return None


def _documents(source):
    """Parsed JSON documents from parsed data, a path, a folder, or a list of paths."""
    paths = source if isinstance(source, (list, tuple)) else [source]
    if not all(isinstance(p, (str, Path)) for p in paths) or not paths:
        yield source
        return
    for p in map(Path, paths):
        for f in sorted(x for x in p.rglob("*") if x.suffix in (".json", ".jsonl")) if p.is_dir() else [p]:
            text = f.read_text(encoding="utf-8")
            yield [json.loads(ln) for ln in text.splitlines() if ln.strip()] if f.suffix == ".jsonl" \
                else json.loads(text)


def all_records(source) -> list[dict]:
    """Logs, events, and alerts from any mix of sources, oldest first."""
    recs = []
    for doc in _documents(source):
        kind = classify(doc)
        if kind is None and isinstance(doc, list):  # several parsed documents, such as [events, alerts, logs]
            recs += [r for d in doc for r in all_records(d)]
            continue
        recs += list(records(doc) if kind == "logs" else k8s_events(doc) if kind == "events" else
                     alerts(doc) if kind == "alerts" else [])
    return sorted((r for r in recs if r["ts"]), key=lambda r: r["ts"])


def _load_config(config) -> dict:
    if config is None or isinstance(config, dict):
        return dict(config or {})
    path = Path(config)
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        need("otel", "tomli")
        import tomli as tomllib
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _ns(iso: str) -> int:
    d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    return int((d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp() * 1e9)


def _iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def incident_start(groups: dict, t0: int, span: int) -> int | None:
    """When the incident started: the first error from a group that was not already erroring
    at the start of the export. Errors present from the beginning are background noise."""
    firsts = [rs[0]["ts"] for rs in groups.values()
              if max(r["sev"] for r in rs) >= 17 and rs[0].get("src") != "alert"]  # alerts lag behind the cause
    new = [ts for ts in firsts if ts > t0 + span * 0.1]
    return min(new or firsts) if firsts else None


def minutes(seconds: float) -> str:
    m = round(seconds / 60)
    return ("under a minute" if m < 1 else "about a minute" if m == 1 else f"about {m} minutes" if m < 90
            else f"about {round(m / 60)} hours")


def frequency(count: int) -> str:
    return "once" if count == 1 else "a few times" if count < 10 else "often" if count < 100 else "very often"


class OtelAdapter(Adapter):
    """Options (config file, dict, or keyword arguments to `extract`):

    min_severity    "warn" (default), "error", "info", ... or a severity number
    incident_start  ISO time. Default: the first error-or-worse record
    window          [start, end] ISO times; groups with no records inside are dropped
    healthcheck     regular expression for noise messages (default: health, readiness, heartbeat, ...)
    send_attributes record attributes whose most common value is sent to Jev
    """

    name = "otel"
    version = "1"
    renderer = "timeline"
    extra = "otel"
    reasons = REASONS

    def __init__(self, config=None):
        register_reasons(REASONS)
        self.config: dict = _load_config(config)

    def configure(self, config) -> None:
        self.config = _load_config(config)

    def extract(self, source, **options) -> Extracted:
        c = {**self.config, **options}
        recs = all_records(source)
        if not recs:
            raise ValueError("no records found. Expected OTLP JSON with `resourceLogs`, Kubernetes events, "
                             "or Alertmanager or Prometheus alerts")

        t0 = recs[0]["ts"]
        t1 = max(max(r["ts"], r.get("end", 0)) for r in recs)
        span = max(t1 - t0, 1)
        send = c.get("send_attributes", SEND_ATTRIBUTES)

        groups: dict[tuple, list] = {}
        for r in recs:
            key = (r["src"], r["service"], level_of(r["sev"]), template(r["body"]))
            groups.setdefault(key, []).append(r)
        start = _ns(c["incident_start"]) if c.get("incident_start") else incident_start(groups, t0, span)

        facts = []
        for i, ((src, service, level, tmpl), rs) in enumerate(sorted(groups.items(), key=lambda kv: kv[1][0]["ts"])):
            first, last = rs[0]["ts"], max(r.get("end", r["ts"]) for r in rs)
            count = sum(r.get("n", 1) for r in rs)
            attrs = {"service": service, "severity": level, "frequency": frequency(count)}
            if src == "event":
                attrs = {"source": "Kubernetes event", "reason": rs[0]["attrs"]["reason"],
                         "object": f"{rs[0]['attrs']['object_kind']} {service}".strip(), **attrs}
            elif src == "alert":
                a = rs[-1]
                end = a["alert_end"] if a["state"] == "resolved" and a["alert_end"] else t1
                last = max(last, end)
                attrs = {"source": "alert", "alert": a["attrs"]["alertname"], "service": service,
                         "severity": a["attrs"]["severity_label"] or level, "state": a["state"],
                         ("fired_for" if a["state"] == "resolved" else "firing_for"): minutes((end - first) / 1e9)}
            if start is not None:
                d = (first - start) / 1e9
                attrs["first_seen"] = ("before the incident" if d < -NEAR_S else
                                       "at the incident start" if d <= NEAR_S else "after the incident started")
            if src == "alert":
                attrs["still_happening"] = "no" if rs[-1]["state"] == "resolved" else "yes"
            else:
                attrs["still_happening"] = "yes" if (t1 - last) / 1e9 <= NEAR_S else "no"
            for key in send:
                values = Counter(str(r["attrs"][key]) for r in rs if r["attrs"].get(key) is not None)
                if values:
                    attrs[key] = values.most_common(1)[0][0]
            if len(tmpl) > 70:
                attrs["message"] = tmpl[:200]
            kind, fid, prefix = {
                "log": (f"{level} log", fact_id("otel", service, level, tmpl), service),
                "event": ("Kubernetes event", fact_id("otel-event", service, level, tmpl),
                          f"{attrs.get('reason')} {attrs.get('object')}"),
                "alert": ("alert", fact_id("otel-alert", service, tmpl), f"alert {service}"),
            }[src]
            facts.append(Fact(
                id=fid,
                kind=kind,
                label=clean_label(f"{prefix}: {tmpl}"),
                attrs=attrs,
                meta={"sev": max(r["sev"] for r in rs), "count": count, "first_ns": first, "last_ns": last,
                      "template": tmpl, "order": i, "records": rs[-300:], "src": src,
                      "reason": rs[0]["attrs"].get("reason"), "state": rs[-1].get("state"),
                      "view": {"start": round((first - t0) / span, 4), "end": round((last - t0) / span, 4),
                               "count": count, **({} if src == "log" else {"source": src})}},
            ))
        source_info = {"name": Path(source).name if isinstance(source, (str, Path)) else "signals",
                       "records": len(recs), "window": [_iso(t0), _iso(t1)]}
        if start is not None:
            source_info["incident_start"] = _iso(start)
            source_info["marker"] = round((start - t0) / span, 4)
        return Extracted(facts, source_info)

    def rules(self) -> RuleSet:
        c = self.config
        hidden, disabled, unlabeled, goal_match, duplicate = CORE_RULES
        min_sev = c.get("min_severity", "warn")
        min_sev = TEXT_LEVELS.get(str(min_sev).lower(), 13) if not isinstance(min_sev, int) else min_sev
        noise = re.compile(c.get("healthcheck", HEALTHCHECK_PATTERN), re.I)
        window = [_ns(t) for t in c["window"]] if c.get("window") else None

        def outside(f, ctx):
            return window and (f.meta["last_ns"] < window[0] or f.meta["first_ns"] > window[1])

        def is_noise(f):  # logs only: a failed Kubernetes probe is a real signal
            return f.meta.get("src", "log") == "log" and bool(
                noise.search(f.meta["template"]) or noise.search(str(f.attrs.get("http.route", ""))))

        def resolved_early(f):
            return f.meta.get("src") == "alert" and f.meta.get("state") == "resolved" \
                and f.attrs.get("first_seen") == "before the incident" and f.attrs.get("still_happening") == "no"

        def attr_match(f, ctx):
            text = " ".join(str(f.attrs.get(k, "")) for k in ("service", "exception.type", "http.route", "peer.service",
                                                              "reason", "alert"))
            return not ctx.matches(f.label) and ctx.matches(text.replace(".", " ").replace("/", " "))

        return RuleSet([
            hidden, disabled, unlabeled,
            Rule(ROUTINE_EVENT, lambda f, ctx: Drop(ROUTINE_EVENT)
                 if f.meta.get("src") == "event" and f.meta.get("reason") in ROUTINE_REASONS else None),
            Rule(RESOLVED_ALERT, lambda f, ctx: Drop(RESOLVED_ALERT) if resolved_early(f) else None),
            Rule(BELOW_SEVERITY, lambda f, ctx: Drop(BELOW_SEVERITY) if f.meta["sev"] < min_sev else None),
            Rule(HEALTHCHECK, lambda f, ctx: Drop(HEALTHCHECK) if is_noise(f) else None),
            Rule(OUTSIDE_WINDOW, lambda f, ctx: Drop(OUTSIDE_WINDOW) if outside(f, ctx) else None),
            goal_match,
            Rule("otel.goal_match_attrs", lambda f, ctx: Boost(0.35, "otel.goal_match_attrs") if attr_match(f, ctx) else None),
            Rule("otel.error", lambda f, ctx: Boost(0.15, "otel.error") if f.meta["sev"] >= 17 else None),
            Rule("otel.early", lambda f, ctx: Boost(0.15, "otel.early")
                 if f.attrs.get("first_seen") == "at the incident start" else None),
            duplicate,
        ])

    def packs(self):
        pack = _CausePack(
            "likely_cause",
            "Incident: {goal}\n"
            "Each item in `log_groups` is a group of similar log messages. Which one group most likely shows the "
            "cause of this incident, rather than a symptom of it?",
            lambda f: f"{f.label} ({f.attrs.get('severity')}, {f.attrs.get('frequency')}, "
                      f"{f.attrs.get('first_seen', 'time unknown')}"
                      f"{', ' + f.attrs['state'] if f.attrs.get('state') else ''})",
            none_text="None of these log groups explains the incident",
        )
        return {pack.name: pack}

    def state(self, goal, kept, source):
        return {"incident": goal, ("signals" if _mixed(kept) else "log_groups"): [f.state() for f in kept]}

    def raw(self, facts):
        """What a naive integration sends: the most recent raw log lines, one fact each."""
        lines = sorted((r for f in facts for r in f.meta.get("records", [])), key=lambda r: r["ts"])[-254:]
        return [Fact(id=fact_id("otel-raw", str(r["ts"]), r["body"], str(i)), kind=level_of(r["sev"]),
                     label=clean_label(f"{_raw_prefix(r)}{r['service']}: {r['body']}"),
                     attrs={"time": _iso(r["ts"]), "severity": level_of(r["sev"])},
                     meta={"order": i, "template": template(r["body"])})
                for i, r in enumerate(lines)]


def _raw_prefix(r: dict) -> str:
    if r.get("src") == "event":
        return f"{r['attrs']['reason']} {r['attrs']['object_kind']} "
    return "alert " if r.get("src") == "alert" else ""


def _mixed(kept) -> bool:
    return any(f.meta.get("src", "log") != "log" for f in kept)


class _CausePack(FactChoice):
    """likely_cause, worded for log groups alone (unchanged) or for logs, Kubernetes events, and alerts together."""

    def build(self, goal, kept, state):
        qs = super().build(goal, kept, state)
        if _mixed(kept):
            q = qs[self.primary]
            q["instructions"] = (
                f"Incident: {goal}\nEach item in `signals` is a group of similar log messages, a group of similar "
                "Kubernetes events, or an alert. Which one signal most likely shows the cause of this incident, "
                "rather than a symptom of it?")
            q["criteria"][next(k for k in q["criteria"] if k not in {f.id for f in kept})] = \
                "None of these signals explains the incident"
        return qs
