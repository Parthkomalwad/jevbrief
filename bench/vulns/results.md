# vulns adapter benchmark

Run on 2026-09-27 with `jev-1.13.0`: 72 cases from [VEX-Bench](https://github.com/steven1518/vex-bench) (MIT, EMNLP 2026, [paper](https://arxiv.org/abs/2609.08040)), collected by `fetch_vexbench.py`. 3 runs per task and arm, 432 calls in all.

**Question:** is this vulnerability actually exploitable in this project? It is asked as the pack's `exploitable` Noul, and a probability above 0.5 means yes. **Right answer:** the security experts' VEX-Bench label. Of the 72 cases, 21 are exploitable and 51 are not, across 34 real repositories in Go, Java, and Python.

**The two arms:**
- **raw:** the alerts as a scanner reports them, with advisory text, severity, version, and fix, and no code search.
- **jevbrief:** the same alerts, plus what the adapter found in the project's code at that commit:
  - whether the package is imported, and whether only in tests
  - whether it is a direct dependency
  - where the advisory names them (mostly Go), whether the vulnerable functions are called

  Alerts for packages never imported, or used only in tests, are dropped.

## Results

| Arm | Accuracy | Median input tokens | Median latency (ms) | Median confidence | Median options |
|---|---|---|---|---|---|
| raw | 63% (137/216) | 876 | 326 | 0.88 | 2 |
| jevbrief | 59% (127/216) | 633 | 324 | 0.99 | 1 |

| Baseline | Accuracy |
|---|---|
| always "not exploitable" | **71%** (51/72) |
| AI agents that read the whole repository (the paper, best models) | about 80% |

**jevbrief scored below the raw arm, and both scored below always answering "not exploitable".** They fail in opposite ways:

| | raw | jevbrief |
|---|---|---|
| Answered "exploitable" | 56 of 216 calls | 122 of 216 calls |
| Exploitable cases caught (recall) | 20 of 63 (32%) | **48 of 63 (76%)** |
| False alarms on non-exploitable cases | **36 of 153 (24%)** | 74 of 153 (48%) |
| Balanced accuracy (the mean of recall and specificity) | 54% | **64%** |

## What happened

- **The code search helps when it can rule a case out.** On 19 cases the adapter dropped every alert, because the package was never imported or only used in tests. Jev then answered "not exploitable" 45 of 57 times. All 12 misses are 4 exploitable cases where the vulnerable package is used through another library, which an import search cannot see.
- **"Imported" is read as "exploitable".** When an alert survives, the facts "imported: yes, used in production code, direct dependency" push Jev toward yes. But most non-exploitable cases in VEX-Bench (38 of 51 before the three exclusions) are "code not reachable": the package is used, just not its vulnerable part. An import search cannot tell those apart, and a call-path analysis would be needed.
- **Vulnerable-function checks are too rare to matter.** OSV names the vulnerable functions for only 11 of the 72 cases, all Go. Where the code does not call any, the experts agree it is not exploitable 5 of 5 times. Where it does, the call was still unreachable in 4 of 6.
- **For triage, the trade can still be useful.** A team using jevbrief would see 76% of the exploitable cases flagged, against 32% for the raw alerts, at the cost of twice the false alarms. On plain accuracy the raw arm wins. The facts are honest, but they are not enough evidence for a yes or no answer.

## Notes

- **The labels are the experts', unchanged.** The collector changes no label. Three of VEX-Bench's 75 cases are excluded, because no OSV advisory names a package in the project's ecosystem, so no scanner would report them:
  - minikube with CVE-2019-5736 (runc)
  - quarkus with CVE-2024-1300
  - llama_index with CVE-2025-6176
- **The prompt and facts were not changed after seeing these results.** They were written before the run, and changing them now would be tuning on the test set. Any change needs a new, separate set to be measured on.
- **Inputs are built from OSV, not from running a scanner.** Each case's alerts come from the CVE's OSV records (the CVE and its GHSA, GO, and PYSEC aliases), keeping only packages in the project's own ecosystem.
- **Checkouts:** each repository is fetched at the task's commit, with only source files and manifests written out. That is 3.5 GB, not committed. The first read of freshly written files was slow on Windows, because antivirus scans each file once. Later reads took seconds.
- **Small set:** 72 cases, with imbalanced labels.

## Per task

| Task | raw | jevbrief |
|---|---|---|
| prestodb-presto-8136f7c-CVE-2024-47535: prestodb/presto | 3/3 | 3/3 |
| apache-pulsar-137df29-CVE-2024-51504: apache/pulsar | 0/3 | 3/3 |
| apache-dubbo-218aab1-CVE-2024-7254: apache/dubbo | 1/3 | 0/3 |
| prestodb-presto-368bcc7-CVE-2025-58457: prestodb/presto | 3/3 | 3/3 |
| quarkusio-quarkus-d392404-CVE-2017-18640: quarkusio/quarkus | 3/3 | 0/3 |
| quarkusio-quarkus-34accfc-CVE-2023-28867: quarkusio/quarkus | 0/3 | 0/3 |
| redisson-redisson-47f6a39-CVE-2020-25638: redisson/redisson | 3/3 | 3/3 |
| quarkusio-quarkus-f4a1bce-CVE-2021-20218: quarkusio/quarkus | 3/3 | 0/3 |
| apache-flink-e4ea3d8-CVE-2025-48924: apache/flink | 3/3 | 0/3 |
| alibaba-nacos-20caf99-CVE-2025-55752: alibaba/nacos | 3/3 | 3/3 |
| apache-airflow-3dbad4f-CVE-2023-47248: apache/airflow | 0/3 | 0/3 |
| fastapi-fastapi-febf6b6-CVE-2024-47874: fastapi/fastapi | 3/3 | 3/3 |
| infiniflow-ragflow-c68767a-CVE-2024-36039: infiniflow/ragflow | 3/3 | 3/3 |
| langflow-ai-langflow-c46a3ee-CVE-2024-23342: langflow-ai/langflow | 3/3 | 3/3 |
| pallets-flask-708d62d-CVE-2023-46136: pallets/flask | 3/3 | 3/3 |
| caddyserver-caddy-8dc7667-CVE-2025-29785: caddyserver/caddy | 3/3 | 3/3 |
| aquasecurity-trivy-37da98d-CVE-2024-32473: aquasecurity/trivy | 3/3 | 3/3 |
| juanfont-headscale-e172c29-CVE-2024-45338: juanfont/headscale | 3/3 | 3/3 |
| zeromicro-go-zero-bae061a-CVE-2022-32149: zeromicro/go-zero | 0/3 | 0/3 |
| cilium-cilium-43bff35-CVE-2026-35469: cilium/cilium | 3/3 | 3/3 |
| containers-podman-6541fc4-CVE-2025-58181: containers/podman | 0/3 | 0/3 |
| rancher-rancher-4dc4f53-CVE-2025-47914: rancher/rancher | 0/3 | 3/3 |
| rancher-rancher-4dc4f53-CVE-2025-58181: rancher/rancher | 0/3 | 0/3 |
| cilium-cilium-3977f6a-CVE-2026-33186: cilium/cilium | 3/3 | 0/3 |
| moby-moby-3ede246-CVE-2026-39984: moby/moby | 3/3 | 3/3 |
| kubernetes-kubernetes-e196d24-CVE-2023-44487: kubernetes/kubernetes | 1/3 | 3/3 |
| kubernetes-kubernetes-1ee2acb-CVE-2024-24786: kubernetes/kubernetes | 0/3 | 0/3 |
| stretchr-testify-285adcc-CVE-2022-28948: stretchr/testify | 0/3 | 3/3 |
| labstack-echo-fdacff0-CVE-2020-26160: labstack/echo | 3/3 | 0/3 |
| aquasecurity-trivy-98e136e-CVE-2024-24791: aquasecurity/trivy | 3/3 | 0/3 |
| containers-podman-38ccfa2-CVE-2024-37298: containers/podman | 3/3 | 0/3 |
| containers-podman-6a65597-CVE-2023-48795: containers/podman | 3/3 | 0/3 |
| cilium-cilium-1228cbc-CVE-2026-35469: cilium/cilium | 0/3 | 0/3 |
| helm-helm-b76a950-CVE-2024-25621: helm/helm | 3/3 | 3/3 |
| rancher-rancher-8761419-CVE-2026-24051: rancher/rancher | 3/3 | 3/3 |
| rancher-rancher-8761419-CVE-2026-39883: rancher/rancher | 3/3 | 3/3 |
| istio-istio-042afc3-CVE-2023-48795: istio/istio | 3/3 | 3/3 |
| istio-istio-8903f65-CVE-2024-45338: istio/istio | 3/3 | 3/3 |
| helm-helm-fbb24fe-CVE-2021-21334: helm/helm | 3/3 | 3/3 |
| kubernetes-kubernetes-ec78c0f-CVE-2021-3121: kubernetes/kubernetes | 0/3 | 3/3 |
| mitmproxy-mitmproxy-ab470e5-CVE-2026-27448: mitmproxy/mitmproxy | 3/3 | 2/3 |
| containers-podman-5ae6347-CVE-2025-47914: containers/podman | 3/3 | 0/3 |
| gitleaks-gitleaks-f487f85-CVE-2025-22871: gitleaks/gitleaks | 3/3 | 3/3 |
| kubernetes-kubernetes-6d4b94f-CVE-2022-41717: kubernetes/kubernetes | 0/3 | 0/3 |
| moby-moby-caea5f7-CVE-2026-39883: moby/moby | 3/3 | 3/3 |
| quarkusio-quarkus-8280c53-CVE-2022-21724: quarkusio/quarkus | 0/3 | 0/3 |
| apache-hadoop-3bf43b4-CVE-2024-47535: apache/hadoop | 0/3 | 3/3 |
| apache-flink-46cbe8b-CVE-2025-12183: apache/flink | 2/3 | 3/3 |
| apache-flink-46cbe8b-CVE-2025-66566: apache/flink | 0/3 | 3/3 |
| keycloak-keycloak-9b01bf3-CVE-2022-3143: keycloak/keycloak | 1/3 | 0/3 |
| apache-pulsar-5e6e6ce-CVE-2023-2976: apache/pulsar | 3/3 | 3/3 |
| apache-hadoop-ff451f5-CVE-2025-66566: apache/hadoop | 1/3 | 3/3 |
| apache-hadoop-c528566-CVE-2025-14763: apache/hadoop | 3/3 | 0/3 |
| apache-dubbo-1d1bb26-CVE-2023-6378: apache/dubbo | 3/3 | 3/3 |
| home-assistant-core-44293a3-CVE-2021-21330: home-assistant/core | 3/3 | 3/3 |
| home-assistant-core-cd0e983-CVE-2023-38325: home-assistant/core | 3/3 | 0/3 |
| infiniflow-ragflow-c68767a-CVE-2024-28219: infiniflow/ragflow | 0/3 | 0/3 |
| infiniflow-ragflow-c68767a-CVE-2024-34069: infiniflow/ragflow | 3/3 | 3/3 |
| infiniflow-ragflow-5c955a3-CVE-2026-28804: infiniflow/ragflow | 1/3 | 0/3 |
| infiniflow-ragflow-5c955a3-CVE-2026-31826: infiniflow/ragflow | 0/3 | 0/3 |
| langchain-ai-langchain-fa6397d-CVE-2024-21503: langchain-ai/langchain | 3/3 | 3/3 |
| langflow-ai-langflow-374508c-CVE-2024-1135: langflow-ai/langflow | 0/3 | 0/3 |
| mitmproxy-mitmproxy-0ace627-CVE-2023-30861: mitmproxy/mitmproxy | 3/3 | 2/3 |
| mitmproxy-mitmproxy-3214581-CVE-2020-8927: mitmproxy/mitmproxy | 1/3 | 3/3 |
| mitmproxy-mitmproxy-b089c5f-CVE-2025-43859: mitmproxy/mitmproxy | 3/3 | 3/3 |
| roboflow-supervision-1bbe03c-CVE-2024-35195: roboflow/supervision | 3/3 | 3/3 |
| run-llama-llama_index-f1124cf-CVE-2024-3651: run-llama/llama_index | 0/3 | 0/3 |
| keycloak-keycloak-731414e-CVE-2019-17571: keycloak/keycloak | 3/3 | 3/3 |
| apache-hadoop-5b1346f-CVE-2024-23944: apache/hadoop | 0/3 | 3/3 |
| apache-pulsar-7ab9c70-CVE-2023-34462: apache/pulsar | 0/3 | 0/3 |
| apache-flink-0630952-CVE-2022-42003: apache/flink | 3/3 | 0/3 |
| spring-projects-spring-boot-1fecd4b-CVE-2021-44228: spring-projects/spring-boot | 0/3 | 3/3 |
