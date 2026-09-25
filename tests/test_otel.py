from pathlib import Path

from jevbrief import Briefing
from jevbrief.adapters.otel import OtelAdapter, frequency, incident_start, template
from jevbrief.testing import FakeJev, check_adapter

BENCH = Path(__file__).resolve().parent.parent / "bench" / "otel"
T0 = 1_790_000_000_000_000_000  # ns


def rec(sec, sev, body, **attrs):
    return {"timeUnixNano": str(T0 + int(sec * 1e9)), "severityNumber": sev, "body": {"stringValue": body},
            "attributes": [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()]}


def export(service, *records):
    return {"resourceLogs": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
                              "scopeLogs": [{"logRecords": list(records)}]}]}


def brief(data, goal="checkout fails", **config):
    b = Briefing(OtelAdapter(config), goal, trace=None, jev=FakeJev())
    b.extract(data)
    return b


DATA = [
    export("api", rec(0, 9, "GET /healthz 200", **{"http.route": "/healthz"}), rec(5, 5, "cache hits=10"),
           rec(1, 17, "background job failed"), *[rec(600 + i, 17, f"call to payments failed: status 503 for order {i}")
                                                   for i in range(12)],
           rec(700, 13, "retrying request 5"), rec(1800, 9, "GET /readyz 200")),
    export("payments", rec(590, 17, "database pool exhausted (waiting=40)"), rec(620, 17, "database pool exhausted (waiting=41)"),
           rec(640, 13, "health check: no healthy upstream for db")),
]


def test_contract():
    check_adapter(OtelAdapter(), BENCH / "checkout_500.json", goal="Checkout requests fail with 500 errors")


def test_templates_group_and_keep_status_codes():
    assert template("call to payments failed: status 503 for order 4521") == "call to payments failed: status 503 for order <n>"
    assert template("pool (max=50, waiting=37) after 812ms") == "pool (max=<n>, waiting=<n>) after <n>"
    assert template("from 10.0.4.17:6379 user a@b.co id 3f2a9c1e7b4d8e0f") == "from <ip> user <email> id <id>"


def test_frequency_buckets():
    assert [frequency(n) for n in (1, 5, 50, 500)] == ["once", "a few times", "often", "very often"]


def test_every_reason_code_and_attrs():
    b = brief(DATA)
    by = {f.meta["template"]: f for f in b.facts}
    assert by["GET /healthz 200"].reason == "otel.below_severity"   # info is below warn
    assert by["cache hits=<n>"].reason == "otel.below_severity"
    cause = by["database pool exhausted (waiting=<n>)"]
    symptom = by["call to payments failed: status 503 for order <n>"]
    assert cause.kept and cause.attrs["first_seen"] == "at the incident start" and cause.attrs["frequency"] == "a few times"
    assert symptom.kept and symptom.attrs["frequency"] == "often"
    assert by["background job failed"].attrs["first_seen"] == "before the incident"
    assert by["retrying request <n>"].attrs["still_happening"] == "no"
    assert by["health check: no healthy upstream for db"].reason == "otel.healthcheck"

    b = brief(DATA, min_severity="info")
    assert {f.meta["template"]: f.reason for f in b.facts}["GET /healthz 200"] == "otel.healthcheck"

    b = brief(DATA, window=["2026-09-21T14:13:20Z", "2026-09-21T14:13:50Z"])  # the first 30 seconds only
    late = {f.meta["template"]: f.reason for f in b.facts if f.meta["first_ns"] > T0 + 60e9 and f.meta["sev"] >= 13}
    assert late["database pool exhausted (waiting=<n>)"] == "otel.outside_window"
    assert set(late.values()) == {"otel.outside_window", "otel.healthcheck"}  # health check is dropped first


def test_incident_start_ignores_errors_already_happening():
    b = brief(DATA)
    groups = {("s", "error", "a"): [{"ts": 0, "sev": 17}], ("s", "error", "b"): [{"ts": 500, "sev": 17}]}
    assert incident_start(groups, 0, 1000) == 500
    assert b.source["incident_start"].endswith("Z") and 0 < b.source["marker"] < 1


def test_timeline_view_in_trace(tmp_path):
    b = Briefing(OtelAdapter(), "checkout fails", trace=str(tmp_path / "t.jsonl"), jev=FakeJev())
    b.extract(DATA)
    r = b.decide().record
    assert r.adapter["renderer"] == "timeline"
    assert all(0 <= f["view"]["start"] <= f["view"]["end"] <= 1 for f in r.facts)


def test_raw_arm_is_raw_lines():
    b = brief(DATA)
    raw = OtelAdapter().raw(b.facts)
    assert len(raw) == 20 and raw[0].label == "api: GET /healthz 200"  # oldest first, unfiltered
    assert all("time" in f.attrs for f in raw)


# Incident pack: Kubernetes events and alerts on the same timeline as the logs.

def iso(sec):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(T0 / 1e9 + sec, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event(sec, reason, message, kind="Pod", name="payments-7d9f8b6c4-x2k9q", type="Warning", count=1, last=None):
    return {"kind": "Event", "type": type, "reason": reason, "message": message, "count": count,
            "involvedObject": {"kind": kind, "name": name, "namespace": "shop"},
            "firstTimestamp": iso(sec), "lastTimestamp": iso(sec if last is None else last)}


EVENTS = {"kind": "List", "apiVersion": "v1", "items": [
    event(0, "Scheduled", "Successfully assigned shop/payments-7d9f8b6c4-x2k9q", type="Normal"),
    event(5, "Pulled", "Container image already present", type="Normal"),
    event(585, "OOMKilling", "Memory cgroup out of memory: Killed process 4121 (java)", kind="Node", name="node-3"),
    event(595, "BackOff", "Back-off restarting failed container payments", count=14, last=1790),
    event(600, "Unhealthy", "Readiness probe failed: HTTP probe failed with statuscode: 503", count=30, last=1795),
]}
ALERTS = [  # Alertmanager /api/v2/alerts
    {"labels": {"alertname": "HighErrorRate", "service": "api", "severity": "critical"},
     "annotations": {"summary": "5xx rate above 5%"}, "startsAt": iso(660), "endsAt": iso(99999),
     "status": {"state": "active"}},
    {"labels": {"alertname": "DiskAlmostFull", "service": "logging", "severity": "warning"},
     "annotations": {"summary": "disk 91% full"}, "startsAt": iso(10), "endsAt": iso(120),
     "status": {"state": "resolved"}},
]


def mixed(tmp_path):
    (tmp_path / "logs.json").write_text(__import__("json").dumps(DATA[1]), encoding="utf-8")
    (tmp_path / "events.json").write_text(__import__("json").dumps(EVENTS), encoding="utf-8")
    (tmp_path / "alerts.json").write_text(__import__("json").dumps(ALERTS), encoding="utf-8")
    return tmp_path


def by_label(b):
    return {f.label: f for f in b.facts}


def test_contract_with_events_and_alerts(tmp_path):
    check_adapter(OtelAdapter(), mixed(tmp_path), goal="Checkout requests fail with 503 errors")


def test_routine_event():
    b = by_label(brief([EVENTS, DATA[1]]))
    assert b["Scheduled Pod payments: Successfully assigned shop/payments-7d9f8b6c<n>-x2k9q"].reason == "otel.routine_event"
    assert b["Pulled Pod payments: Container image already present"].reason == "otel.routine_event"


def test_resolved_alert():
    b = by_label(brief([ALERTS, DATA[1]]))
    old = b["alert logging: DiskAlmostFull: disk <n>% full"]
    assert old.reason == "otel.resolved_alert" and old.attrs["state"] == "resolved" and old.attrs["fired_for"] == "about 2 minutes"
    firing = b["alert api: HighErrorRate: 5xx rate above <n>%"]
    assert firing.kept and firing.attrs["still_happening"] == "yes" and firing.attrs["first_seen"] == "after the incident started"  # alerts lag the cause


def test_resolved_during_the_incident_is_kept():
    late = [{**ALERTS[1], "startsAt": iso(600), "endsAt": iso(700)}]
    f = next(f for f in brief([late, DATA[1]]).facts if f.kind == "alert")
    assert f.kind == "alert" and f.kept


def test_event_attrs_and_probe_is_not_healthcheck_noise():
    b = by_label(brief([EVENTS, DATA[1]]))
    backoff = b["BackOff Pod payments: Back-off restarting failed container payments"]
    assert backoff.kept and backoff.attrs == {
        "source": "Kubernetes event", "reason": "BackOff", "object": "Pod payments", "service": "payments",
        "severity": "warn", "frequency": "often", "first_seen": "at the incident start", "still_happening": "yes"}
    probe = next(f for label, f in b.items() if label.startswith("Unhealthy Pod payments: Readiness probe failed"))
    assert probe.kept and probe.attrs["frequency"] == "often"  # counted from the event's `count`, 14 and 30


def test_incident_start_ignores_alerts():
    only_alert_then_error = [ALERTS[:1], export("api", rec(0, 9, "boot"), rec(900, 17, "db down"))]
    b = brief(only_alert_then_error)
    assert b.source["incident_start"] == iso(900)


def test_event_and_alert_formats():
    v2 = {"kind": "EventList", "items": [{"reason": "FailedScheduling", "note": "0/3 nodes are available",
                                          "type": "Warning", "regarding": {"kind": "Pod", "name": "web-0"},
                                          "eventTime": iso(5), "series": {"count": 3, "lastObservedTime": iso(50)}}]}
    prom = {"status": "success", "data": {"alerts": [{"labels": {"alertname": "TargetDown", "job": "node"},
                                                      "annotations": {}, "state": "firing", "activeAt": iso(1)}]}}
    hook = {"status": "firing", "alerts": [{"status": "firing", "labels": {"alertname": "PodCrashLooping",
            "severity": "critical", "namespace": "shop"}, "annotations": {"description": "crash looping"},
            "startsAt": iso(2), "endsAt": "0001-01-01T00:00:00Z"}]}
    labels = {f.label: f for f in brief([v2, prom, hook], goal="site down").facts}
    assert "FailedScheduling Pod web: <n>/<n> nodes are available" in labels
    assert labels["alert node: TargetDown"].attrs["state"] == "firing"
    assert labels["alert shop: PodCrashLooping: crash looping"].attrs["severity"] == "critical"


def test_mixed_question_and_state(tmp_path):
    b = brief(mixed(tmp_path))
    q = b.pack.build("g", b.kept, b.state())["likely_cause"]
    assert "Kubernetes events, or an alert" in q["instructions"] and "signals" in b.state()
    assert q["criteria"]["none"] == "None of these signals explains the incident"
    b = brief(DATA)
    assert "log_groups" in b.state() and "Kubernetes" not in b.pack.build("g", b.kept, b.state())["likely_cause"]["instructions"]


def test_viewer_tags_the_source(tmp_path):
    b = Briefing(OtelAdapter(), "checkout fails", trace=str(tmp_path / "t.jsonl"), jev=FakeJev())
    b.extract([EVENTS, ALERTS, DATA[1]])
    r = b.decide().record
    assert {f["view"].get("source") for f in r.facts} == {None, "event", "alert"}
    raw = OtelAdapter().raw(b.facts)
    assert any(f.label.startswith("BackOff Pod payments:") for f in raw) and any(f.label.startswith("alert api:") for f in raw)
