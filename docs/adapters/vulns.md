# vulns adapter

Triage for security alerts. It drops alerts for packages your code never imports or only uses in tests, flags vulnerabilities being exploited in the wild, and asks Jev which alert to fix first. Standard library only.

| | |
|---|---|
| **Reads** | osv-scanner, grype, trivy, GitHub Dependabot alerts, or OSV advisories, plus optionally your source code |
| **Jev answers** | Which alert to fix first. Experimental: whether an alert is actually exploitable in your project |
| **Install** | `pip install jevbrief`. Standard library only. |
| **Main API** | `Briefing(VulnsAdapter(), goal)` and `--adapter vulns` |
| **Benchmark** | 72 expert-labeled cases (VEX-Bench): **below** the always-"no" baseline on "is it exploitable?" (59% against 71%). It finds 76% of the exploitable cases, against 32% for the raw alerts |

## Quick start

```bash
osv-scanner scan --format json -r . > alerts.json
jevbrief inspect alerts.json --adapter vulns --goal "payments service" --config vulns.toml
jevbrief ask     alerts.json --adapter vulns --goal "payments service" --config vulns.toml --view
```

With `vulns.toml`:

```toml
source_dir = "."               # search the code: imports, test-only use, calls to vulnerable functions
kev = "known_exploited.json"   # optional: CISA's KEV catalog, from cisa.gov
```

## Python

```python
from jevbrief import Briefing
from jevbrief.adapters.vulns import VulnsAdapter

brief = Briefing(VulnsAdapter(), goal="payments service", trace="traces/vulns.jsonl")
brief.extract(["osv.json", "dependabot.json"], source_dir=".", kev="known_exploited.json")
for f in brief.facts:
    print(f.label, "->", "kept" if f.kept else f"dropped: {f.reason}")
decision = brief.decide()
print("fix first:", decision.fact.label if decision.fact else "none")
```

## Input

It reads any mix of these:
- `osv-scanner --format json`
- `grype -o json`
- `trivy ... --format json`
- GitHub Dependabot alerts (`/repos/{owner}/{repo}/dependabot/alerts`). Only open alerts are read.
- OSV advisories (`https://api.osv.dev/v1/vulns/<id>`), one or a list

Pass a file, a folder, a list of paths, or the parsed JSON.

## What Jev sees

One fact per alert:

| Attribute | Values |
|---|---|
| `package`, `version` | From the scanner |
| `severity` | `critical`, `high`, `medium`, `low`, or `unknown`, from the label or the CVSS score |
| `fix_available` | `yes` or `no` |
| `known_exploited` | `yes` when the CVE is in CISA's KEV catalog (with `kev`) |
| `dependency` | `direct` or `transitive`, from the scanner, or from `go.mod` (not `// indirect`), requirements files, or `pom.xml` |
| `imported` | `yes` or `no`: does the code import the package? It handles Go import paths, Python module names (`PyYAML` is imported as `yaml`), and Java package prefixes (with `source_dir`) |
| `used_in` | `production code` or `tests only` (with `source_dir`) |
| `calls_vulnerable_code` | `yes` or `no`, when the advisory names the vulnerable functions. OSV does this mostly for Go (with `source_dir`) |
| `summary` | The advisory's summary |

## Reason codes

| Rule | Effect |
|---|---|
| `vulns.tests_only` | Drops alerts for packages used only in tests, or declared as development dependencies |
| `vulns.not_imported` | Drops alerts for packages the code never imports (with `source_dir`) |
| `vulns.duplicate_cve` | Drops the same vulnerability in the same package when it is reported again (for example as a CVE by one scanner and a GHSA by another) |
| `vulns.known_exploited` | +0.3 for vulnerabilities on CISA's KEV list |
| `vulns.vulnerable_code_called` | +0.2 when the code calls a function the advisory names as vulnerable |
| Severity | Up to +0.2 for critical |
| Core | `unlabeled`, `goal_match`, `low_score`, `budget` |

## Options

Pass a config file with `--config vulns.toml`, a dict to `VulnsAdapter({...})`, or keyword arguments to `extract()`:
- `source_dir`: the project's source folder. Without it, no alert is dropped as not imported, and Jev sees the advisory's vulnerable functions instead.
- `kev`: a path to CISA's Known Exploited Vulnerabilities JSON.

## Question pack

`fix_first` asks two questions in one call:
- **A Choice:** which alert should be fixed first, because it is the most likely to be exploitable, plus "None of these alerts looks exploitable in this project".
- **`exploitable`, a Noul (experimental):** is at least one of the alerts actually exploitable here? Read it from `decision.answers["exploitable"]["noul"]`. The benchmark below shows it is weak: use it to rank, not to close alerts.

## Benchmark

[bench/vulns/results.md](../../bench/vulns/results.md) uses 72 real cases from [VEX-Bench](https://github.com/steven1518/vex-bench): a repository at a commit, one CVE, and security experts' verdict on whether it is exploitable there (21 yes, 51 no). The question is the `exploitable` Noul, with 3 runs per case.

| | Accuracy | Exploitable cases found | False alarms |
|---|---|---|---|
| always "not exploitable" (free) | **71%** | 0% | 0% |
| raw: the alerts, no code search | 63% | 32% | 24% |
| jevbrief: alerts plus code search | 59% | **76%** | 48% |
| AI agents that read the whole repository (the paper) | about 80% | | |

**What works:**
- When the code never imports the package, or only uses it in tests, the adapter drops the alert, and Jev then answers "not exploitable" 45 of 57 times.
- Jevbrief finds more than twice as many of the exploitable cases.

**What does not:** when a package is imported, Jev reads that as exploitable. But most non-exploitable cases (38 of 51) are "code not reachable": the package is used, just not its vulnerable part. An import search cannot see that difference.

To rebuild the set, run `python bench/vulns/fetch_vexbench.py`. It needs git and about 3.5 GB of checkouts.

## Limits

- **No call-path analysis.** "Imported" is not "reachable". Deciding whether the vulnerable code is actually reached needs a call graph, such as govulncheck for Go. That is the biggest gap.
- **Indirect use is missed.** A package used only through another library is dropped as "not imported", even when it is exploitable: 4 of the 21 exploitable benchmark cases.
- **Vulnerable functions are known only for some advisories.** OSV lists them mostly for Go.
- **The benchmark's inputs come from OSV advisories, not a scanner run on each project.**
