"""Generate synthetic OpenTelemetry incidents (OTLP JSON) for the otel adapter benchmark.

Each incident is a 30-minute log export from six services. The root cause starts a few minutes
in and is buried under health checks, request logs, a background error that was already
happening before the incident, and many symptom errors from other services.

Run: python bench/otel/make_data.py
"""

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = datetime(2026, 9, 24, 14, 0, tzinfo=timezone.utc)
SERVICES = ["api-gateway", "checkout", "payments", "inventory", "auth", "notifications"]
SEV = {"debug": (5, "DEBUG"), "info": (9, "INFO"), "warn": (13, "WARN"), "error": (17, "ERROR"), "fatal": (21, "FATAL")}


class Export:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.logs: dict[str, list] = {s: [] for s in SERVICES}

    def log(self, service, minute, level, body, **attrs):
        ts = BASE + timedelta(minutes=minute, seconds=self.rng.uniform(0, 59))
        num, text = SEV[level]
        rec = {"timeUnixNano": str(int(ts.timestamp() * 1e9)), "severityNumber": num, "severityText": text,
               "body": {"stringValue": body},
               "attributes": [{"key": k, "value": {"intValue": str(v)} if isinstance(v, int) else {"stringValue": str(v)}}
                              for k, v in attrs.items()]}
        self.logs[service].append(rec)

    def noise(self, background_error=None):
        r = self.rng
        for minute in range(30):
            for s in SERVICES:
                for _ in range(4):
                    self.log(s, minute, "info", "GET /healthz 200", **{"http.route": "/healthz"})
                self.log(s, minute, "debug", f"cache stats hits={r.randint(900, 999)} misses={r.randint(1, 40)}")
            for _ in range(8):
                route = r.choice(["/products", "/cart", "/checkout", "/login", "/orders"])
                self.log("api-gateway", minute, "info", f"{route} completed in {r.randint(20, 180)}ms",
                         **{"http.route": route, "http.response.status_code": 200})
            if minute % 4 == 0:
                self.log("inventory", minute, "warn", f"slow query on stock_levels took {r.randint(600, 900)}ms",
                         **{"db.system": "postgresql"})
            if minute % 6 == 0:
                self.log("auth", minute, "info", f"session refreshed for user {r.randint(1000, 9999)}")
            if background_error and minute % 3 == 0:
                service, body = background_error
                self.log(service, minute, "error", body.format(n=r.randint(1000, 9999)))

    def write(self, path):
        data = {"resourceLogs": [
            {"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": s}}]},
             "scopeLogs": [{"scope": {"name": "app"}, "logRecords": recs}]} for s, recs in self.logs.items()]}
        path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def incident(seed, name, background, cause, symptoms, start=8):
    e = Export(seed)
    e.noise(background)
    service, level, body, attrs, every = cause
    for minute in range(start, 30 if every else start + 1, every or 1):
        e.log(service, minute, level, body.format(n=e.rng.randint(10, 99)), **attrs)
    for s_service, s_level, s_body, s_attrs, per_minute in symptoms:
        for minute in range(start + 1, 30):
            for _ in range(per_minute):
                e.log(s_service, minute, s_level, s_body.format(n=e.rng.randint(1000, 9999)), **s_attrs)
    e.write(HERE / f"{name}.json")


INCIDENTS = [
    ("checkout_500", "Checkout requests started failing with 500 errors",
     ("inventory", "failed to refresh exchange rates from provider: 429 Too Many Requests"),
     ("payments", "error", "database connection pool exhausted (max=50, waiting={n})", {"db.system": "postgresql"}, 1),
     [("checkout", "error", "call to payments failed: status 503 for order {n}", {"peer.service": "payments"}, 6),
      ("api-gateway", "error", "upstream returned 500 for /checkout request {n}", {"http.route": "/checkout", "http.response.status_code": 500}, 6)],
     "database connection pool exhausted"),
    ("login_down", "Users cannot log in anymore",
     ("notifications", "push provider returned 410 for device token {n}"),
     ("auth", "error", "failed to load token signing key: certificate expired", {"exception.type": "CertificateExpiredError"}, 2),
     [("auth", "error", "token validation failed for session {n}", {}, 5),
      ("api-gateway", "warn", "401 returned for /login request {n}", {"http.route": "/login", "http.response.status_code": 401}, 8)],
     "certificate expired"),
    ("slow_products", "Product pages are very slow and some time out",
     ("payments", "webhook signature mismatch for event {n}"),
     ("inventory", "error", "cache cluster unreachable: connect ECONNREFUSED 10.0.4.17:6379", {"exception.type": "ConnectionRefusedError"}, 1),
     [("inventory", "warn", "falling back to database for product {n}", {}, 6),
      ("api-gateway", "error", "request to /products timed out after 30000ms (req {n})", {"http.route": "/products"}, 4)],
     "cache cluster unreachable"),
    ("no_emails", "Customers say they are not getting order confirmation emails",
     ("inventory", "failed to refresh exchange rates from provider: 429 Too Many Requests"),
     ("notifications", "error", "SMTP authentication failed for user mailer@example.com", {"peer.service": "smtp"}, 3),
     [("notifications", "warn", "email job {n} failed, retry scheduled", {}, 4),
      ("checkout", "warn", "order {n} confirmation not acknowledged by notifications", {}, 2)],
     "SMTP authentication failed"),
    ("deploy_502", "Every request returns 502 since the last deploy",
     ("notifications", "push provider returned 410 for device token {n}"),
     ("api-gateway", "error", "config reload failed: unknown field 'upstreams.timeoutz' in gateway.yaml", {}, 0),
     [("api-gateway", "error", "no healthy upstream for request {n}", {"http.response.status_code": 502}, 9),
      ("checkout", "warn", "gateway returned 502 for callback {n}", {}, 2)],
     "config reload failed"),
    ("stock_errors", "Orders fail with an out of stock error even though items are in stock",
     ("payments", "webhook signature mismatch for event {n}"),
     ("inventory", "error", "stock sync job crashed: KeyError 'warehouse_id'", {"exception.type": "KeyError"}, 5),
     [("checkout", "error", "order {n} rejected: item out of stock", {}, 3),
      ("api-gateway", "warn", "409 returned for /orders request {n}", {"http.route": "/orders", "http.response.status_code": 409}, 3)],
     "stock sync job crashed"),
]

if __name__ == "__main__":
    tasks = []
    for i, (name, goal, background, cause, symptoms, expected) in enumerate(INCIDENTS):
        incident(100 + i, name, background, cause, symptoms)
        tasks.append({"adapter": "otel", "source": f"{name}.json", "goal": goal, "expected_contains": expected})
    (HERE / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(tasks)} incidents and tasks.json to {HERE}")
