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
