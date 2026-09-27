import json

from jevbrief import Briefing
from jevbrief.adapters.vulns import VulnsAdapter, classify, read_alerts
from jevbrief.testing import FakeJev, check_adapter

# osv-scanner output for a small project with Go, Python, and Java dependencies.
OSV_SCANNER = {"results": [
    {"source": {"path": "/repo/go.mod", "type": "lockfile"}, "packages": [
        {"package": {"name": "golang.org/x/net", "version": "0.15.0", "ecosystem": "Go"},
         "groups": [{"ids": ["GO-2023-2102"], "max_severity": "7.5"}],
         "vulnerabilities": [{"id": "GO-2023-2102", "aliases": ["CVE-2023-39325", "GHSA-4374-p667-p6c8"],
                              "summary": "HTTP/2 rapid reset can cause excessive work in net/http",
                              "affected": [{"package": {"name": "golang.org/x/net", "ecosystem": "Go"},
                                            "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "0.17.0"}]}],
                                            "ecosystem_specific": {"imports": [{"path": "golang.org/x/net/http2",
                                                                                "symbols": ["Server.ServeConn", "serverConn.serve"]}]}}]}]},
        {"package": {"name": "github.com/gorilla/websocket", "version": "1.4.0", "ecosystem": "Go"},
         "groups": [{"ids": ["GO-2020-0019"], "max_severity": "7.5"}],
         "vulnerabilities": [{"id": "GO-2020-0019", "aliases": ["CVE-2020-27813"], "summary": "Integer overflow in websocket",
                              "affected": [{"package": {"name": "github.com/gorilla/websocket", "ecosystem": "Go"},
                                            "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.4.1"}]}],
                                            "ecosystem_specific": {"imports": [{"path": "github.com/gorilla/websocket",
                                                                                "symbols": ["Conn.NextReader", "Conn.ReadMessage"]}]}}]}]},
    ]},
    {"source": {"path": "/repo/requirements.txt", "type": "lockfile"}, "packages": [
        {"package": {"name": "PyYAML", "version": "5.3", "ecosystem": "PyPI"},
         "groups": [{"ids": ["GHSA-8q59-q68h-6hv4"], "max_severity": "9.8"}],
         "vulnerabilities": [{"id": "GHSA-8q59-q68h-6hv4", "aliases": ["CVE-2020-14343"], "summary": "Arbitrary code execution in full_load",
                              "affected": [{"package": {"name": "PyYAML", "ecosystem": "PyPI"},
                                            "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "5.4"}]}]}]}]},
        {"package": {"name": "pytest", "version": "6.0.0", "ecosystem": "PyPI"},
         "groups": [{"ids": ["PYSEC-2022-42969"], "max_severity": "5.3"}],
         "vulnerabilities": [{"id": "PYSEC-2022-42969", "aliases": ["CVE-2022-42969"], "summary": "ReDoS in py library",
                              "affected": [{"package": {"name": "pytest", "ecosystem": "PyPI"},
                                            "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}]}]}]}]},
        {"package": {"name": "requests", "version": "2.19.0", "ecosystem": "PyPI"},
         "groups": [{"ids": ["PYSEC-2018-28"], "max_severity": "7.5"}],
         "vulnerabilities": [{"id": "PYSEC-2018-28", "aliases": ["CVE-2018-18074"], "summary": "Authorization header leak on redirect",
                              "affected": [{"package": {"name": "requests", "ecosystem": "PyPI"},
                                            "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.20.0"}]}]}]}]},
    ]},
]}

# The same PyYAML vulnerability, reported again by grype under its GHSA ID.
GRYPE = {"matches": [{"vulnerability": {"id": "GHSA-8q59-q68h-6hv4", "severity": "Critical",
                                        "fix": {"versions": ["5.4"], "state": "fixed"}, "description": "full_load RCE"},
                      "relatedVulnerabilities": [{"id": "CVE-2020-14343"}],
                      "artifact": {"name": "PyYAML", "version": "5.3", "type": "python",
                                   "locations": [{"path": "/requirements.txt"}]}}]}

TRIVY = {"Results": [{"Target": "pom.xml", "Type": "pom", "Vulnerabilities": [
    {"VulnerabilityID": "CVE-2021-44228", "PkgName": "org.apache.logging.log4j:log4j-core", "InstalledVersion": "2.14.1",
     "FixedVersion": "2.15.0", "Severity": "CRITICAL", "Title": "Log4Shell: remote code execution"}]}]}

DEPENDABOT = [{"number": 7, "state": "open",
               "dependency": {"package": {"ecosystem": "pip", "name": "jinja2"}, "manifest_path": "requirements-dev.txt",
                              "scope": "development", "relationship": "direct"},
               "security_advisory": {"ghsa_id": "GHSA-h5c8-rqwp-cp95", "cve_id": "CVE-2024-22195", "summary": "XSS in xmlattr",
                                     "severity": "medium"},
               "security_vulnerability": {"first_patched_version": {"identifier": "3.1.3"}, "severity": "medium"}},
              {"number": 8, "state": "fixed", "dependency": {"package": {"ecosystem": "pip", "name": "urllib3"}},
               "security_advisory": {"ghsa_id": "GHSA-x", "summary": "already fixed", "severity": "high"},
               "security_vulnerability": {}}]

KEV = {"vulnerabilities": [{"cveID": "CVE-2021-44228"}, {"cveID": "CVE-2023-39325"}]}


def project(tmp_path):
    """A small project: Go serves HTTP/2, Python loads YAML, Java logs, pytest is only in tests."""
    src = tmp_path / "repo"
    (src / "cmd").mkdir(parents=True)
    (src / "app").mkdir()
    (src / "tests").mkdir()
    (src / "src/main/java/app").mkdir(parents=True)
    (src / "go.mod").write_text("module example.com/app\n\nrequire (\n\tgolang.org/x/net v0.15.0\n"
                                "\tgithub.com/gorilla/websocket v1.4.0 // indirect\n)\n", encoding="utf-8")
    (src / "cmd/main.go").write_text('package main\n\nimport (\n\t"net/http"\n\t"golang.org/x/net/http2"\n)\n\n'
                                     "func main() {\n\ts := &http2.Server{}\n\ts.ServeConn(nil, nil)\n\t_ = http.ListenAndServe\n}\n",
                                     encoding="utf-8")
    (src / "requirements.txt").write_text("PyYAML==5.3\nrequests==2.19.0\n", encoding="utf-8")
    (src / "app/config.py").write_text("import yaml\n\ndef load(p):\n    return yaml.full_load(open(p))\n", encoding="utf-8")
    (src / "tests/test_app.py").write_text("import pytest\n\ndef test_ok():\n    assert True\n", encoding="utf-8")
    (src / "pom.xml").write_text("<project><dependency><artifactId>log4j-core</artifactId></dependency></project>",
                                 encoding="utf-8")
    (src / "src/main/java/app/Main.java").write_text(
        "package app;\nimport org.apache.logging.log4j.LogManager;\nclass Main { }\n", encoding="utf-8")
    alerts = tmp_path / "alerts"
    alerts.mkdir()
    for name, data in (("osv.json", OSV_SCANNER), ("grype.json", GRYPE), ("trivy.json", TRIVY), ("dependabot.json", DEPENDABOT)):
        (alerts / name).write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "kev.json").write_text(json.dumps(KEV), encoding="utf-8")
    return alerts, src, tmp_path / "kev.json"


def brief(tmp_path, goal="payments service", **options):
    alerts, src, kev = project(tmp_path)
    b = Briefing(VulnsAdapter(), goal, trace=None, jev=FakeJev())
    b.extract(alerts, **{"source_dir": src, "kev": kev, **options})
    return b


def by_label(b):
    return {f.label: f for f in b.facts}


def test_contract(tmp_path):
    alerts, src, kev = project(tmp_path)
    check_adapter(VulnsAdapter({"source_dir": str(src), "kev": str(kev)}), alerts, goal="payments service")


def test_every_input_format():
    assert [classify(d) for d in (OSV_SCANNER, GRYPE, TRIVY, DEPENDABOT, OSV_SCANNER["results"][0]["packages"][0]["vulnerabilities"][0])] \
        == ["osv-scanner", "grype", "trivy", "dependabot", "osv"]
    assert len(read_alerts(OSV_SCANNER)) == 5 and read_alerts(TRIVY)[0]["fixed"] == "2.15.0"
    assert [a["package"] for a in read_alerts(DEPENDABOT)] == ["jinja2"]  # the fixed alert is skipped
    record = read_alerts(OSV_SCANNER["results"][0]["packages"][0]["vulnerabilities"][0])[0]
    assert record["cve"] == "CVE-2023-39325" and record["symbols"] == ["Server.ServeConn", "serverConn.serve"]


def test_tests_only(tmp_path):
    b = by_label(brief(tmp_path))
    assert b["CVE-2022-42969 in pytest"].reason == "vulns.tests_only"      # imported only under tests/
    assert b["CVE-2024-22195 in jinja2"].reason == "vulns.tests_only"      # Dependabot: development scope


def test_not_imported(tmp_path):
    b = by_label(brief(tmp_path))
    assert b["CVE-2018-18074 in requests"].reason == "vulns.not_imported"
    assert b["CVE-2020-27813 in github.com/gorilla/websocket"].reason == "vulns.not_imported"


def test_duplicate_cve(tmp_path):
    pyyaml = [f for f in brief(tmp_path).facts if f.meta["package"] == "PyYAML"]
    assert len(pyyaml) == 2 and sum(f.kept for f in pyyaml) == 1  # osv-scanner and grype report the same CVE
    assert [f.reason for f in pyyaml if not f.kept] == ["vulns.duplicate_cve"]


def test_known_exploited(tmp_path):
    f = by_label(brief(tmp_path))["CVE-2021-44228 in org.apache.logging.log4j:log4j-core"]
    assert f.kept and f.reason == "vulns.known_exploited" and f.attrs["known_exploited"] == "yes"
    assert f.attrs["imported"] == "yes" and f.attrs["dependency"] == "direct" and f.attrs["severity"] == "critical"


def test_vulnerable_code_called(tmp_path):
    b = brief(tmp_path, kev=None)  # without the KEV list, the call is the reason it is kept
    f = by_label(b)["CVE-2023-39325 in golang.org/x/net"]
    assert f.kept and f.reason == "vulns.vulnerable_code_called"
    assert f.attrs == {"package": "golang.org/x/net", "severity": "high", "version": "0.15.0", "fix_available": "yes",
                       "dependency": "direct", "imported": "yes", "used_in": "production code",
                       "calls_vulnerable_code": "yes",
                       "summary": "HTTP/2 rapid reset can cause excessive work in net/http"}


def test_without_source_the_advisory_functions_are_listed():
    b = Briefing(VulnsAdapter(), "service", trace=None, jev=FakeJev())
    b.extract(OSV_SCANNER)
    f = next(f for f in b.facts if f.meta["package"] == "golang.org/x/net")
    assert "imported" not in f.attrs and f.attrs["vulnerable_functions"] == "Server.ServeConn, serverConn.serve"


def test_question_pack(tmp_path):
    b = brief(tmp_path)
    qs = b.pack.build("payments service", b.kept, b.state())
    assert set(qs) == {"fix_first", "exploitable"} and qs["exploitable"]["type"] == "noul"


def test_raw_arm_has_no_code_search(tmp_path):
    b = brief(tmp_path)
    raw = VulnsAdapter().raw(b.facts)
    assert len(raw) == len(b.facts) and all("imported" not in f.attrs and "known_exploited" not in f.attrs for f in raw)
