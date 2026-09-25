"""Generate synthetic incidents with logs, Kubernetes events, and alerts, for the otel incident pack benchmark.

Each incident is a folder with a 30-minute OTLP log export (the same noise as bench/otel), a
`kubectl get events -o json` file, and an Alertmanager `/api/v2/alerts` file. Every incident also has
background noise across all three sources:
- routine rollout events (Scheduled, Pulling, Pulled, Created, Started)
- an HPA warning event that was already repeating before the incident
- a CPU throttling alert that fires the whole time, and an old alert that resolved before the incident

The root cause is in the events for five incidents, in an alert for one, and in the logs for two, where
loud alerts and probe failures are only symptoms.

Run: python bench/incident/make_data.py
"""

import json
import sys
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "otel"))

from make_data import BASE, Export  # noqa: E402  (bench/otel/make_data.py)

START = 8  # the incident starts at minute 8


def iso(minute: float) -> str:
    return (BASE + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Incident(Export):
    def __init__(self, seed):
        super().__init__(seed)
        self.events: list[dict] = []
        self.alerts: list[dict] = []

    def event(self, minute, reason, message, kind="Pod", name="checkout-7d9f8b6c4-x2k9q", warning=True,
              count=1, until=None):
        self.events.append({
            "kind": "Event", "apiVersion": "v1", "type": "Warning" if warning else "Normal", "reason": reason,
            "message": message, "count": count, "metadata": {"name": f"{name}.{len(self.events):x}", "namespace": "shop"},
            "involvedObject": {"kind": kind, "name": name, "namespace": "shop"},
            "firstTimestamp": iso(minute), "lastTimestamp": iso(until if until is not None else minute)})

    def alert(self, minute, name, service, severity, summary, resolved_at=None):
        self.alerts.append({
            "labels": {"alertname": name, "service": service, "severity": severity, "namespace": "shop"},
            "annotations": {"summary": summary}, "startsAt": iso(minute),
            "endsAt": iso(resolved_at if resolved_at is not None else 34),
            "status": {"state": "resolved" if resolved_at is not None else "active"}})

    def background(self, background_error):
        self.noise(background_error)
        for i, svc in enumerate(["checkout", "payments", "inventory"]):  # a routine rollout at the start
            pod = f"{svc}-5c8d7f9b6-{'abcde'[i]}{i}k2p"
            for step, (reason, msg) in enumerate([("Scheduled", f"Successfully assigned shop/{pod} to node-2"),
                                                  ("Pulling", f'Pulling image "registry.shop/{svc}:1.42.0"'),
                                                  ("Pulled", f'Successfully pulled image "registry.shop/{svc}:1.42.0"'),
                                                  ("Created", f"Created container {svc}"),
                                                  ("Started", f"Started container {svc}")]):
                self.event(i + step * 0.2, reason, msg, name=pod, warning=False)
        self.event(0, "FailedGetResourceMetric", "failed to get cpu utilization: missing request for cpu in container sidecar",
                   kind="HorizontalPodAutoscaler", name="notifications", count=60, until=30)
        self.alert(-120, "CPUThrottlingHigh", "notifications", "warning", "notifications is throttled 31% of the time")
        self.alert(1, "KubeJobFailed", "reports", "warning", "Job shop/nightly-report failed to complete", resolved_at=3)

    def write_all(self, folder: Path):
        folder.mkdir(exist_ok=True)
        self.write(folder / "logs.json")
        (folder / "events.json").write_text(json.dumps({"kind": "List", "apiVersion": "v1", "items": self.events}) + "\n",
                                            encoding="utf-8")
        (folder / "alerts.json").write_text(json.dumps(self.alerts) + "\n", encoding="utf-8")

    def symptom_logs(self, service, level, body, per_minute, start=START + 1, **attrs):
        for minute in range(start, 30):
            for _ in range(per_minute):
                self.log(service, minute, level, body.format(n=self.rng.randint(1000, 9999)), **attrs)


def oom_checkout(e: Incident):
    e.event(START, "OOMKilling", "Memory cgroup out of memory: Killed process 4121 (java) total-vm:4194304kB",
            kind="Node", name="node-2", count=9, until=29)
    e.event(START + 0.5, "BackOff", "Back-off restarting failed container checkout", count=40, until=29.5)
    e.event(START + 1, "Unhealthy", "Readiness probe failed: Get \"http://10.0.3.8:8080/ready\": connection refused",
            count=55, until=29.6)
    e.symptom_logs("api-gateway", "error", "upstream returned 503 for /checkout request {n}", 6,
                   **{"http.route": "/checkout", "http.response.status_code": 503})
    e.alert(START + 2, "HighErrorRate", "api-gateway", "critical", "5xx rate on /checkout above 5%")


def image_pull(e: Incident):
    pod = "payments-6b9c4d7f8-q7w2e"
    e.event(START, "Pulling", 'Pulling image "registry.shop/payments:1.43.0"', name=pod, warning=False)
    e.event(START + 0.1, "Failed", 'Failed to pull image "registry.shop/payments:1.43.0": manifest unknown',
            name=pod, count=12, until=29)
    e.event(START + 0.2, "BackOff", 'Back-off pulling image "registry.shop/payments:1.43.0"', name=pod, count=80, until=29.5)
    e.symptom_logs("checkout", "error", "call to payments failed: status 503 for order {n}", 5,
                   **{"peer.service": "payments"})
    e.alert(START + 3, "KubeDeploymentReplicasMismatch", "payments", "warning",
            "Deployment shop/payments has not matched the expected number of replicas")


def cert_alert(e: Incident):
    e.alert(START, "TLSCertificateExpired", "auth", "critical", "TLS certificate for auth.shop.internal has expired")
    e.symptom_logs("api-gateway", "error", "upstream connect error or disconnect/reset before headers (req {n})", 6)
    e.symptom_logs("auth", "warn", "login attempt {n} aborted by client", 4)
    e.alert(START + 2, "LoginSuccessRateLow", "auth", "critical", "login success rate below 50%")


def disk_pressure(e: Incident):
    e.event(START, "EvictionThresholdMet", "Attempting to reclaim ephemeral-storage", kind="Node", name="node-3",
            count=6, until=20)
    e.event(START + 0.3, "Evicted", "The node was low on resource: ephemeral-storage. Container inventory was using 9Gi",
            name="inventory-7f8d6c5b4-z9x8c", count=4, until=18)
    e.symptom_logs("api-gateway", "error", "request to /products timed out after 30000ms (req {n})", 3,
                   **{"http.route": "/products"})
    e.symptom_logs("inventory", "warn", "falling back to database for product {n}", 4)
    e.alert(START + 4, "HighLatency", "api-gateway", "warning", "p99 latency on /products above 5s")


def coredns_crash(e: Incident):
    e.event(START, "BackOff", "Back-off restarting failed container coredns", name="coredns-5d78c9869d-4xq7t",
            count=30, until=29)
    for svc in ("checkout", "payments", "inventory"):  # every service logs DNS failures: loud symptoms
        e.symptom_logs(svc, "error", "dial tcp: lookup postgres.shop.svc.cluster.local: no such host (conn {n})", 4)
    e.alert(START + 2, "HighErrorRate", "api-gateway", "critical", "5xx rate above 5% on all routes")


def quota(e: Incident):
    e.event(START, "FailedCreate", 'Error creating: pods "orders-8c7d6-" is forbidden: exceeded quota: compute-resources, '
            "requested: cpu=500m, used: cpu=8, limited: cpu=8", kind="ReplicaSet", name="orders-8c7d6", count=15, until=29)
    e.event(START, "SuccessfulRescale", "New size: 12; reason: cpu resource utilization above target",
            kind="HorizontalPodAutoscaler", name="orders", warning=False)
    e.symptom_logs("api-gateway", "warn", "request to /orders took {n}ms", 6, **{"http.route": "/orders"})
    e.alert(START + 3, "HighLatency", "api-gateway", "warning", "p99 latency on /orders above 3s")


def pool_logs(e: Incident):  # hard: the cause is a log group; alerts and probe failures are symptoms
    for minute in range(START, 30):
        e.log("payments", minute, "error", f"database connection pool exhausted (max=50, waiting={e.rng.randint(10, 99)})",
              **{"db.system": "postgresql"})
    e.symptom_logs("checkout", "error", "call to payments failed: status 503 for order {n}", 6, **{"peer.service": "payments"})
    e.event(START + 1, "Unhealthy", "Readiness probe failed: HTTP probe failed with statuscode: 503",
            name="payments-6b9c4d7f8-m3n4b", count=70, until=29.5)
    e.alert(START + 2, "HighErrorRate", "checkout", "critical", "5xx rate on checkout above 5%")
    e.alert(START + 3, "SLOBurnRateHigh", "checkout", "critical", "checkout error budget burning 14x too fast")


def config_log(e: Incident):  # hard: one quiet log line; the rollout events look like the obvious change
    pod = "api-gateway-66f7d8c9b-h2j3k"
    for step, (reason, msg) in enumerate([("Scheduled", f"Successfully assigned shop/{pod} to node-1"),
                                          ("Pulled", 'Container image "registry.shop/gateway:2.8.0" already present'),
                                          ("Created", "Created container gateway"), ("Started", "Started container gateway")]):
        e.event(START - 0.5 + step * 0.1, reason, msg, name=pod, warning=False)
    e.log("api-gateway", START, "error", "config reload failed: unknown field 'upstreams.timeoutz' in gateway.yaml")
    e.symptom_logs("api-gateway", "error", "no healthy upstream for request {n}", 8, **{"http.response.status_code": 502})
    e.alert(START + 1, "HighErrorRate", "api-gateway", "critical", "5xx rate above 5% on all routes")


INCIDENTS = [
    (oom_checkout, "Checkout keeps failing with 503 errors", "out of memory", "event"),
    (image_pull, "Payments are failing since the release went out", ["Failed to pull image", "Back-off pulling image"], "event"),
    (cert_alert, "Nobody can log in", "TLSCertificateExpired", "alert"),
    (disk_pressure, "Product pages are timing out", ["ephemeral-storage", "EvictionThresholdMet"], "event"),
    (coredns_crash, "Most requests are failing across the site", "coredns", "event"),
    (quota, "Orders are very slow under the evening load", "exceeded quota", "event"),
    (pool_logs, "Checkout requests started failing with 503 errors", "database connection pool exhausted", "log"),
    (config_log, "Every request returns 502 since a few minutes ago", "config reload failed", "log"),
]
BACKGROUND = [("inventory", "failed to refresh exchange rates from provider: 429 Too Many Requests"),
              ("notifications", "push provider returned 410 for device token {n}"),
              ("payments", "webhook signature mismatch for event {n}")]

if __name__ == "__main__":
    tasks = []
    for i, (build, goal, expected, where) in enumerate(INCIDENTS):
        e = Incident(200 + i)
        e.background(BACKGROUND[i % len(BACKGROUND)])
        build(e)
        e.write_all(HERE / build.__name__)
        tasks.append({"adapter": "otel", "source": build.__name__, "goal": goal, "expected_contains": expected,
                      "cause_in": where})
    (HERE / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(tasks)} incidents and tasks.json to {HERE}")
