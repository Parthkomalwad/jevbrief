"""The otel adapter: OpenTelemetry logs (OTLP JSON) to log-group facts, for finding an incident's cause.

Reads an OTLP JSON export (`{"resourceLogs": [...]}`) or JSON Lines of them, as written by the
OpenTelemetry Collector's `file` exporter. Standard library only.

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
REASONS = {
    BELOW_SEVERITY: "Less severe than the minimum severity (default: warnings and above)",
    HEALTHCHECK: "Health check, readiness, or heartbeat noise",
    OUTSIDE_WINDOW: "No records inside the incident time window",
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
                           "attrs": _attrs(r.get("attributes"))}


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
    firsts = [rs[0]["ts"] for (_, _, _), rs in groups.items() if max(r["sev"] for r in rs) >= 17]
    new = [ts for ts in firsts if ts > t0 + span * 0.1]
    return min(new or firsts) if firsts else None


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
        data = source
        if isinstance(source, (str, Path)):
            path = Path(source)
            text = path.read_text(encoding="utf-8")
            data = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix == ".jsonl" \
                else json.loads(text)
        recs = sorted(records(data), key=lambda r: r["ts"])
        if not recs:
            raise ValueError("no log records found. Expected OTLP JSON with `resourceLogs`")

        t0, t1 = recs[0]["ts"], recs[-1]["ts"]
        span = max(t1 - t0, 1)
        send = c.get("send_attributes", SEND_ATTRIBUTES)

        groups: dict[tuple, list] = {}
        for r in recs:
            key = (r["service"], level_of(r["sev"]), template(r["body"]))
            groups.setdefault(key, []).append(r)
        start = _ns(c["incident_start"]) if c.get("incident_start") else incident_start(groups, t0, span)

        facts = []
        for i, ((service, level, tmpl), rs) in enumerate(sorted(groups.items(), key=lambda kv: kv[1][0]["ts"])):
            first, last = rs[0]["ts"], rs[-1]["ts"]
            attrs = {"service": service, "severity": level, "frequency": frequency(len(rs))}
            if start is not None:
                d = (first - start) / 1e9
                attrs["first_seen"] = ("before the incident" if d < -NEAR_S else
                                       "at the incident start" if d <= NEAR_S else "after the incident started")
            attrs["still_happening"] = "yes" if (t1 - last) / 1e9 <= NEAR_S else "no"
            for key in send:
                values = Counter(str(r["attrs"][key]) for r in rs if r["attrs"].get(key) is not None)
                if values:
                    attrs[key] = values.most_common(1)[0][0]
            if len(tmpl) > 70:
                attrs["message"] = tmpl[:200]
            facts.append(Fact(
                id=fact_id("otel", service, level, tmpl),
                kind=f"{level} log",
                label=clean_label(f"{service}: {tmpl}"),
                attrs=attrs,
                meta={"sev": max(r["sev"] for r in rs), "count": len(rs), "first_ns": first, "last_ns": last,
                      "template": tmpl, "order": i, "records": rs[-300:],
                      "view": {"start": round((first - t0) / span, 4), "end": round((last - t0) / span, 4),
                               "count": len(rs)}},
            ))
        source_info = {"name": Path(source).name if isinstance(source, (str, Path)) else "logs",
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

        def attr_match(f, ctx):
            text = " ".join(str(f.attrs.get(k, "")) for k in ("service", "exception.type", "http.route", "peer.service"))
            return not ctx.matches(f.label) and ctx.matches(text.replace(".", " ").replace("/", " "))

        return RuleSet([
            hidden, disabled, unlabeled,
            Rule(BELOW_SEVERITY, lambda f, ctx: Drop(BELOW_SEVERITY) if f.meta["sev"] < min_sev else None),
            Rule(HEALTHCHECK, lambda f, ctx: Drop(HEALTHCHECK)
                 if noise.search(f.meta["template"]) or noise.search(str(f.attrs.get("http.route", ""))) else None),
            Rule(OUTSIDE_WINDOW, lambda f, ctx: Drop(OUTSIDE_WINDOW) if outside(f, ctx) else None),
            goal_match,
            Rule("otel.goal_match_attrs", lambda f, ctx: Boost(0.35, "otel.goal_match_attrs") if attr_match(f, ctx) else None),
            Rule("otel.error", lambda f, ctx: Boost(0.15, "otel.error") if f.meta["sev"] >= 17 else None),
            Rule("otel.early", lambda f, ctx: Boost(0.15, "otel.early")
                 if f.attrs.get("first_seen") == "at the incident start" else None),
            duplicate,
        ])

    def packs(self):
        pack = FactChoice(
            "likely_cause",
            "Incident: {goal}\n"
            "Each item in `log_groups` is a group of similar log messages. Which one group most likely shows the "
            "cause of this incident, rather than a symptom of it?",
            lambda f: f"{f.label} ({f.attrs.get('severity')}, {f.attrs.get('frequency')}, "
                      f"{f.attrs.get('first_seen', 'time unknown')})",
            none_text="None of these log groups explains the incident",
        )
        return {pack.name: pack}

    def state(self, goal, kept, source):
        return {"incident": goal, "log_groups": [f.state() for f in kept]}

    def raw(self, facts):
        """What a naive integration sends: the most recent raw log lines, one fact each."""
        lines = sorted((r for f in facts for r in f.meta.get("records", [])), key=lambda r: r["ts"])[-254:]
        return [Fact(id=fact_id("otel-raw", str(r["ts"]), r["body"], str(i)), kind=level_of(r["sev"]),
                     label=clean_label(f"{r['service']}: {r['body']}"),
                     attrs={"time": _iso(r["ts"]), "severity": level_of(r["sev"])},
                     meta={"order": i, "template": template(r["body"])})
                for i, r in enumerate(lines)]
