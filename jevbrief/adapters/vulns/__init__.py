"""The vulns adapter: security alerts to facts, for choosing which to fix first and judging if one is exploitable.

Reads any mix of (files, a folder, a list of paths, or parsed JSON):
- `osv-scanner --format json` output
- `grype -o json` output
- `trivy ... --format json` output
- GitHub Dependabot alerts (`/repos/{owner}/{repo}/dependabot/alerts`)
- OSV advisory records (`https://api.osv.dev/v1/vulns/<id>`), one record or a list

With `source_dir`, the project's code is searched, so each alert also says whether the package is imported,
whether it is used only in tests, and, where the advisory names the vulnerable functions (mostly Go), whether
the code calls them. With `kev`, a path to CISA's Known Exploited Vulnerabilities JSON, alerts under active
exploitation are marked. Standard library only.

The `exploitable` question is experimental. On VEX-Bench it scored below always answering "not exploitable"
(see bench/vulns/results.md): an import search cannot tell whether the vulnerable code is reached. Use the
answers to rank alerts, not to close them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ...briefing import Extracted
from ...facts import Fact, clean_label, fact_id
from ...questions import FactChoice
from ...rules import Boost, Context, Drop, GroupRule, Rule, RuleSet, goal_match, unlabeled
from ...sources import find_files
from .. import Adapter

TESTS_ONLY = "vulns.tests_only"
NOT_IMPORTED = "vulns.not_imported"
DUPLICATE_CVE = "vulns.duplicate_cve"
KNOWN_EXPLOITED = "vulns.known_exploited"
CALLED = "vulns.vulnerable_code_called"
REASONS = {
    TESTS_ONLY: "The package is used only in tests or declared as a development dependency",
    NOT_IMPORTED: "The project's code never imports the package",
    DUPLICATE_CVE: "The same vulnerability in the same package, reported again (for example by CVE and GHSA ID)",
    KNOWN_EXPLOITED: "Kept: on CISA's list of vulnerabilities exploited in the wild",
    CALLED: "Kept: the code calls a function the advisory names as vulnerable",
}

SEVERITY = {"critical": 4, "high": 3, "moderate": 2, "medium": 2, "low": 1, "negligible": 0, "unknown": -1}
WORD = {4: "critical", 3: "high", 2: "medium", 1: "low", 0: "negligible", -1: "unknown"}
MAVEN = {"maven", "java-archive", "jar", "gradle", "java", "pom", "gradle-lockfile"}  # names scanners use
SOURCE_SUFFIXES = {".go": "Go", ".py": "PyPI", ".java": "Maven", ".kt": "Maven", ".scala": "Maven", ".groovy": "Maven"}
TEST_PATH = re.compile(r"(^|/)(tests?|testing|testdata|src/test|__tests__|it)(/|$)|_test\.go$|(^|/)test_[^/]*\.py$|Tests?\.(java|kt)$",
                       re.I)
# PyPI distributions whose import name differs from the package name.
PY_IMPORT = {"pyyaml": "yaml", "pillow": "PIL", "beautifulsoup4": "bs4", "scikit-learn": "sklearn",
             "python-dateutil": "dateutil", "protobuf": "google.protobuf", "opencv-python": "cv2",
             "pyjwt": "jwt", "python-jose": "jose", "pycryptodome": "Crypto", "pyopenssl": "OpenSSL",
             "msgpack-python": "msgpack", "python-multipart": "multipart", "gitpython": "git", "pymysql": "pymysql"}


def _severity(*values) -> int:
    """The highest severity among labels ("HIGH", "Moderate") and CVSS base scores ("7.5")."""
    best = -1
    for v in values:
        if v is None or v == "":
            continue
        s = str(v).strip().lower()
        if s in SEVERITY:
            best = max(best, SEVERITY[s])
            continue
        try:
            score = float(s)
        except ValueError:
            continue
        best = max(best, 4 if score >= 9 else 3 if score >= 7 else 2 if score >= 4 else 1 if score > 0 else 0)
    return best


def _cve(ids: Iterable[str]) -> str:
    ids = [i for i in ids if i]
    return next((i for i in ids if i.upper().startswith("CVE-")), ids[0] if ids else "")


def _alert(**kw) -> dict:
    a: dict[str, Any] = {"id": "", "aliases": [], "package": "", "version": "", "ecosystem": "", "severity": -1, "fixed": None,
         "summary": "", "direct": None, "dev": None, "symbols": [], "import_paths": [], "manifest": ""}
    a.update(kw)
    a["cve"] = _cve([a["id"], *a["aliases"]])
    return a


def _osv_fixed(entry: dict, name: str) -> list[str]:
    out = []
    for aff in entry.get("affected", []):
        if not name or aff.get("package", {}).get("name") == name:
            out += [e["fixed"] for r in aff.get("ranges", []) for e in r.get("events", []) if "fixed" in e]
    return out


def _osv_symbols(entry: dict, name: str) -> tuple[list[str], list[str]]:
    """(vulnerable function names, import paths) that the advisory lists, where it does (mostly Go)."""
    symbols, paths = [], []
    for aff in entry.get("affected", []):
        if name and aff.get("package", {}).get("name") != name:
            continue
        for imp in (aff.get("ecosystem_specific") or {}).get("imports", []):
            paths.append(imp.get("path", ""))
            symbols += imp.get("symbols", [])
    return sorted(set(symbols)), [p for p in paths if p]


def from_osv_scanner(data: dict) -> list[dict]:
    out = []
    for result in data.get("results", []):
        manifest = (result.get("source") or {}).get("path", "")
        for pkg in result.get("packages", []):
            p = pkg.get("package", {})
            groups = {i: g.get("max_severity") for g in pkg.get("groups", []) for i in g.get("ids", [])}
            for v in pkg.get("vulnerabilities", []):
                symbols, paths = _osv_symbols(v, p.get("name", ""))
                fixed = _osv_fixed(v, p.get("name", ""))
                out.append(_alert(id=v.get("id", ""), aliases=v.get("aliases", []), package=p.get("name", ""),
                                  version=p.get("version", ""), ecosystem=p.get("ecosystem", ""),
                                  severity=_severity(groups.get(v.get("id")), (v.get("database_specific") or {}).get("severity")),
                                  fixed=fixed[0] if fixed else None, summary=v.get("summary", ""),
                                  dev=(bool(pkg.get("dependency_groups")) and set(pkg["dependency_groups"]) <= {"dev", "test"}) or None,
                                  symbols=symbols, import_paths=paths, manifest=manifest))
    return out


def from_osv_records(records: list[dict]) -> list[dict]:
    """Plain OSV advisories: one alert per affected package."""
    out = []
    for v in records:
        for aff in v.get("affected", []) or [{}]:
            p = aff.get("package", {})
            symbols, paths = _osv_symbols(v, p.get("name", ""))
            fixed = _osv_fixed(v, p.get("name", ""))
            out.append(_alert(id=v.get("id", ""), aliases=v.get("aliases", []), package=p.get("name", ""),
                              ecosystem=p.get("ecosystem", ""), fixed=fixed[0] if fixed else None,
                              severity=_severity((v.get("database_specific") or {}).get("severity"),
                                                 (aff.get("ecosystem_specific") or {}).get("severity")),
                              summary=v.get("summary", "") or v.get("details", "")[:200], symbols=symbols, import_paths=paths))
    return out


def from_grype(data: dict) -> list[dict]:
    out = []
    for m in data.get("matches", []):
        v, art = m.get("vulnerability", {}), m.get("artifact", {})
        fix = v.get("fix") or {}
        out.append(_alert(id=v.get("id", ""), aliases=[r.get("id", "") for r in m.get("relatedVulnerabilities", [])],
                          package=art.get("name", ""), version=art.get("version", ""), ecosystem=art.get("type", ""),
                          severity=_severity(v.get("severity")), fixed=(fix.get("versions") or [None])[0]
                          if fix.get("state") == "fixed" else None, summary=v.get("description", ""),
                          manifest=((art.get("locations") or [{}])[0]).get("path", "")))
    return out


def from_trivy(data: dict) -> list[dict]:
    out = []
    for r in data.get("Results", []):
        for v in r.get("Vulnerabilities") or []:
            out.append(_alert(id=v.get("VulnerabilityID", ""), package=v.get("PkgName", ""),
                              version=v.get("InstalledVersion", ""), ecosystem=r.get("Type", ""),
                              severity=_severity(v.get("Severity")), fixed=v.get("FixedVersion") or None,
                              summary=v.get("Title") or v.get("Description", ""), manifest=r.get("Target", "")))
    return out


def from_dependabot(items: list[dict]) -> list[dict]:
    out = []
    for a in items:
        if a.get("state") not in (None, "open"):
            continue
        dep, adv, vul = a.get("dependency", {}), a.get("security_advisory", {}), a.get("security_vulnerability", {})
        pkg = dep.get("package", {})
        out.append(_alert(id=adv.get("ghsa_id", ""), aliases=[adv.get("cve_id") or ""],
                          package=pkg.get("name", ""), ecosystem=pkg.get("ecosystem", ""),
                          severity=_severity(adv.get("severity"), vul.get("severity")),
                          fixed=(vul.get("first_patched_version") or {}).get("identifier"),
                          summary=adv.get("summary", ""), manifest=dep.get("manifest_path", ""),
                          direct={"direct": True, "transitive": False}.get(dep.get("relationship")),
                          dev={"development": True, "runtime": False}.get(dep.get("scope"))))
    return out


def classify(data) -> str | None:
    if isinstance(data, list):
        first = data[0] if data and isinstance(data[0], dict) else {}
        return "dependabot" if "security_advisory" in first else "osv" if "affected" in first else None
    if not isinstance(data, dict):
        return None
    if "results" in data and any("packages" in r for r in data.get("results", [])):
        return "osv-scanner"
    if "matches" in data:
        return "grype"
    if "Results" in data:
        return "trivy"
    if "affected" in data and "id" in data:
        return "osv"
    return None


PARSERS: dict[str, Callable[[Any], list[dict]]] = {"osv-scanner": from_osv_scanner, "grype": from_grype, "trivy": from_trivy,
           "dependabot": from_dependabot, "osv": lambda d: from_osv_records(d if isinstance(d, list) else [d])}


def read_alerts(source) -> list[dict]:
    docs = [source] if isinstance(source, dict) or (isinstance(source, list) and source
                                                   and isinstance(source[0], dict)) else \
        [json.loads(p.read_text(encoding="utf-8")) for p in find_files(source, (".json",))]
    out = []
    for d in docs:
        kind = classify(d)
        if kind:
            out += [{**a, "scanner": kind} for a in PARSERS[kind](d)]
    return out


# Searching the project's code.

def _py_module(package: str) -> str:
    name = package.lower()
    return PY_IMPORT.get(name, name.replace("-", "_"))


def _import_pattern(alert: dict) -> re.Pattern | None:
    """How the code would import the package, by ecosystem."""
    eco, name = alert["ecosystem"].lower(), alert["package"]
    if not name:
        return None
    if eco in ("go", "gomod", "go-module"):
        paths = alert["import_paths"] or [name]
        return re.compile("|".join(r'"' + re.escape(p) + r'(/[^"]*)?"' for p in paths))
    if eco in ("pypi", "pip", "python", "poetry", "pipenv"):
        mod = re.escape(_py_module(name))
        return re.compile(rf"^\s*(from\s+{mod}(\.|\s)|import\s+{mod}(\.|\s|$|,))", re.M)
    if eco in MAVEN:
        group = name.split(":")[0]
        return re.compile(rf"^\s*import\s+(static\s+)?{re.escape(group)}\.", re.M) if "." in group else None
    return None


def _symbol_pattern(symbols: list[str]) -> re.Pattern | None:
    """Calls to vulnerable functions: "Server.Serve" and "Serve" both match a call to `.Serve(` or `Serve(`."""
    names = sorted({s.rsplit(".", 1)[-1] for s in symbols if s and s[0].isalpha()})
    return re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\s*\(") if names else None


class _Code:
    """The project's source files, read once per extraction."""

    def __init__(self, root: Path):
        self.root = root
        self.files: list[tuple[str, str, str]] = []  # (relative path, ecosystem, text)
        for f in sorted(root.rglob("*")):
            eco = SOURCE_SUFFIXES.get(f.suffix)
            if not eco or not f.is_file() or any(p in (".git", "node_modules", "vendor", ".venv") for p in f.parts):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            self.files.append((f.relative_to(root).as_posix(), eco, text))

    def usage(self, alert: dict) -> dict:
        """imported: yes/no/unknown, used_in: production code/tests only, calls_vulnerable_code: yes/no/unknown."""
        pat = _import_pattern(alert)
        if pat is None:
            return {}
        hits = [(path, text) for path, _, text in self.files if pat.search(text)]
        if not hits:
            return {"imported": "no"}
        prod = [(p, t) for p, t in hits if not TEST_PATH.search(p)]
        out = {"imported": "yes", "used_in": "production code" if prod else "tests only"}
        sym = _symbol_pattern(alert["symbols"])
        if sym is not None:
            out["calls_vulnerable_code"] = "yes" if any(sym.search(t) for _, t in (prod or hits)) else "no"
        return out


def _declared(root: Path, alert: dict) -> bool | None:
    """Whether the package is a direct dependency, from go.mod (not `// indirect`), requirements files, or pom.xml."""
    name, eco = alert["package"], alert["ecosystem"].lower()
    if eco in ("go", "gomod", "go-module"):
        found = False
        for f in root.rglob("go.mod"):
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith(name + " ") or f" {name} " in line:
                    if "// indirect" not in line:
                        return True
                    found = True
        return False if found else None
    if eco in ("pypi", "pip", "python", "poetry", "pipenv"):
        want = re.compile(rf"(^|[\s\"'\[,]){re.escape(name)}\s*([<>=!~;\[\"',\s]|$)", re.I | re.M)
        files = [*root.rglob("requirements*.txt"), *root.rglob("pyproject.toml"), *root.rglob("setup.py"), *root.rglob("setup.cfg")]
        return any(want.search(f.read_text(encoding="utf-8", errors="replace")) for f in files) if files else None
    if eco in MAVEN and ":" in name:
        artifact = name.split(":", 1)[1]
        poms = list(root.rglob("pom.xml")) + list(root.rglob("build.gradle*"))
        return any(artifact in f.read_text(encoding="utf-8", errors="replace") for f in poms) if poms else None
    return None


def _duplicate_cves(facts: list[Fact], ctx: Context) -> None:
    seen: set[tuple[str, str]] = set()
    for f in sorted((f for f in facts if f.kept), key=lambda f: -f.score):
        key = (f.meta["cve"] or f.id, f.meta["package"])
        if key in seen:
            f.drop(DUPLICATE_CVE)
        else:
            seen.add(key)


class VulnsAdapter(Adapter):
    """Options (config dict, file, or keyword arguments to `extract`):

    source_dir   the project's source folder: finds imports, test-only use, and calls to vulnerable functions
    kev          CISA's Known Exploited Vulnerabilities catalog (a path to its JSON)
    """

    name = "vulns"
    version = "1"
    renderer = "table"
    extra = "vulns"
    reasons = REASONS

    def extract(self, source, **options) -> Extracted:
        c = self.settings(options)
        alerts = read_alerts(source)
        if not alerts:
            raise ValueError("no alerts found. Expected osv-scanner, grype, trivy, Dependabot, or OSV JSON")
        kev: set[str] = set()
        if c.get("kev"):
            data = json.loads(Path(c["kev"]).read_text(encoding="utf-8"))
            kev = {v.get("cveID", "") for v in data.get("vulnerabilities", [])}
        root = Path(c["source_dir"]) if c.get("source_dir") else None
        code = _Code(root) if root else None

        facts: list[Fact] = []
        for i, a in enumerate(alerts):
            attrs: dict = {"package": a["package"], "severity": WORD[a["severity"]]}
            if a["version"]:
                attrs["version"] = a["version"]
            attrs["fix_available"] = "yes" if a["fixed"] else "no"
            if a["cve"] in kev:
                attrs["known_exploited"] = "yes"
            direct = a["direct"] if a["direct"] is not None else (_declared(root, a) if root else None)
            if direct is not None:
                attrs["dependency"] = "direct" if direct else "transitive"
            usage = code.usage(a) if code else {}
            attrs.update(usage)
            if a["dev"]:
                attrs["used_in"] = "tests only"
            if a["symbols"] and "calls_vulnerable_code" not in attrs and code is None:
                attrs["vulnerable_functions"] = ", ".join(a["symbols"][:6])
            if a["summary"]:
                attrs["summary"] = " ".join(a["summary"].split())[:200]
            facts.append(Fact(
                id=fact_id("vulns", a.get("scanner", ""), a["id"], a["package"], a["version"], a["manifest"]),
                kind="vulnerability",
                label=clean_label(f"{a['cve'] or a['id']} in {a['package']}"),
                attrs=attrs,
                meta={"order": (-a["severity"], i), "cve": a["cve"], "package": a["package"], "sev": a["severity"],
                      "kev": a["cve"] in kev, "tests_only": attrs.get("used_in") == "tests only",
                      "not_imported": usage.get("imported") == "no",
                      "called": usage.get("calls_vulnerable_code") == "yes", "alert": a},
            ))
        name = Path(source).name if isinstance(source, (str, Path)) else "alerts"
        return Extracted(facts, {"name": name, "alerts": len(alerts), "source_searched": bool(code),
                                 "source_files": len(code.files) if code else 0})

    def rules(self, options: dict | None = None) -> RuleSet:
        return RuleSet([
            unlabeled,
            Rule(TESTS_ONLY, lambda f, ctx: Drop(TESTS_ONLY) if f.meta["tests_only"] else None),
            Rule(NOT_IMPORTED, lambda f, ctx: Drop(NOT_IMPORTED) if f.meta["not_imported"] else None),
            goal_match,
            Rule(KNOWN_EXPLOITED, lambda f, ctx: Boost(0.3, KNOWN_EXPLOITED) if f.meta["kev"] else None),
            Rule(CALLED, lambda f, ctx: Boost(0.2, CALLED) if f.meta["called"] else None),
            Rule("vulns.severity", lambda f, ctx: Boost(0.05 * max(f.meta["sev"], 0)) if f.meta["sev"] > 0 else None),
            GroupRule(DUPLICATE_CVE, _duplicate_cves),
        ])

    def packs(self):
        pack = FactChoice(
            "fix_first",
            "Project: {goal}\nEach item in `alerts` is a known vulnerability in one of the project's dependencies. "
            "Which one alert should be fixed first, because it is the most likely to be exploitable in this project?",
            lambda f: f"{f.label} ({f.attrs.get('severity')}"
                      f"{', exploited in the wild' if f.attrs.get('known_exploited') else ''}"
                      f"{', vulnerable code called' if f.attrs.get('calls_vulnerable_code') == 'yes' else ''})",
            none_text="None of these alerts looks exploitable in this project",
            extra={"exploitable": {"type": "noul", "instructions":
                                   "Project: {goal}\nIs at least one of the vulnerabilities in `alerts` actually "
                                   "exploitable in this project, given how the project uses the package?",
                                   "criteria": {"true": "Exploitable: the project uses the vulnerable code in a reachable way",
                                                "false": "Not exploitable here: the vulnerable code is not present, not "
                                                         "reached, or needs a configuration or environment the project does not have"}}},
        )
        return {pack.name: pack}

    def state(self, goal, kept, source):
        return {"project": goal, "alerts": [f.state() for f in kept]}

    def raw(self, facts):
        """What a naive integration sends: every alert as the scanner reported it, with no code search."""
        out = []
        for f in facts:
            a = f.meta["alert"]
            attrs = {k: a[k] for k in ("id", "aliases", "package", "version", "ecosystem", "fixed", "summary") if a.get(k)}
            attrs["severity"] = WORD[a["severity"]]
            out.append(Fact(id=f.id, kind="vulnerability", label=f.label, attrs=attrs, meta={"order": f.meta["order"]}))
        return out
