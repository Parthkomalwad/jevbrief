"""Collect the VEX-Bench cases for the vulns adapter benchmark.

VEX-Bench (MIT, https://github.com/steven1518/vex-bench, EMNLP 2026) has 75 real cases: a repository at a commit
and one CVE, labeled by security experts as exploitable or not in that repository, with a reason. For each case:
- the repository is checked out at the commit: only that commit is fetched (files over 1 MB left out), and only
  its source files and dependency manifests are written out (`repos/`, not committed)
- the CVE's OSV records are fetched: the CVE record and its GHSA, GO, and PYSEC aliases, which name the
  affected package and, for Go, the vulnerable functions. Only packages in the project's ecosystem are kept,
  as a scanner of the project would report (`cases/<task>.json`, not committed)
- a task is written, scored on the pack's `exploitable` question against the expert label

The labels are the experts' and are not changed. Needs git on PATH.

Run: python bench/vulns/fetch_vexbench.py [--limit 5]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
VEX_BENCH = "80cddeac3132826bfd47227ad59b2e6618a681bd"  # the vex-bench commit these tasks come from
TASKS_URL = f"https://raw.githubusercontent.com/steven1518/vex-bench/{VEX_BENCH}/benchmark/tasks/vex_bench.jsonl"
OSV = "https://api.osv.dev/v1/vulns/{}"
PACKAGE_ALIASES = ("GHSA-", "GO-", "PYSEC-")


def get_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


ECOSYSTEM = {"java": "Maven", "python": "PyPI", "go": "Go"}


def for_project(records: list[dict], language: str) -> list[dict]:
    """Only the affected packages in the project's own ecosystem, as a scanner of that project would report.
    An advisory lists every affected package: protobuf's lists Java, Kotlin, and Ruby packages."""
    want, out = ECOSYSTEM[language], []
    for r in records:
        affected = [a for a in r.get("affected", []) if (a.get("package") or {}).get("ecosystem") == want]
        if affected:
            out.append({**r, "affected": affected})
    return out


def osv_records(cve: str) -> list[dict]:
    """The CVE's OSV record plus its aliases that name packages, deduplicated."""
    first = get_json(OSV.format(cve)) or {"id": cve, "aliases": []}
    records, seen = [], set()
    for rid in [first.get("id", cve), *first.get("aliases", [])]:
        if rid in seen or not (rid == first.get("id") or rid.startswith(PACKAGE_ALIASES)):
            continue
        seen.add(rid)
        rec = first if rid == first.get("id") else get_json(OSV.format(rid))
        if rec and any(a.get("package") for a in rec.get("affected", [])):
            records.append(rec)
    return records


# Only what the adapter reads: source files and dependency manifests. This skips test resources with paths too
# long or names invalid on Windows, and keeps the checkouts small.
SOURCE = (".go", ".py", ".java", ".kt", ".scala", ".groovy")
MANIFESTS = ("go.mod", "pyproject.toml", "setup.py", "setup.cfg", "pom.xml", "build.gradle", "build.gradle.kts")


def _wanted(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.endswith(SOURCE) or name in MANIFESTS or (name.startswith("requirements") and name.endswith(".txt"))


def checkout(repo_url: str, sha: str, dest: Path) -> int:
    """Fetch one commit (files over 1 MB left out) and write out only its source files and manifests.
    Returns the checkout's size in bytes."""
    if not (dest / ".git").exists():
        dest.mkdir(parents=True, exist_ok=True)

        def run(*args, **kw):
            return subprocess.run(["git", *args], cwd=dest, check=True, capture_output=True, **kw)

        run("init", "-q")
        run("config", "core.longpaths", "true")
        run("remote", "add", "origin", repo_url)
        run("fetch", "-q", "--depth", "1", "--filter=blob:limit=1m", "origin", sha)
        run("read-tree", "FETCH_HEAD")
        files = [f for f in run("ls-files", "-z").stdout.decode("utf-8", "replace").split("\0") if f and _wanted(f)]
        run("checkout-index", "-f", "-z", "--stdin", input="\0".join(files).encode("utf-8"))
    return sum(f.stat().st_size for f in dest.rglob("*") if f.is_file() and ".git" not in f.parts)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--limit", type=int, default=0, help="only the first N cases (0: all)")
    args = p.parse_args()
    with urllib.request.urlopen(TASKS_URL, timeout=60) as r:
        rows = [json.loads(line) for line in r.read().decode().splitlines() if line.strip()]
    if args.limit:
        rows = rows[: args.limit]
    (HERE / "cases").mkdir(exist_ok=True)
    tasks, total = [], 0
    for row in rows:
        owner_repo = row["repo_url"].split("github.com/")[1].rstrip("/")
        repo_dir = HERE / "repos" / f"{owner_repo.replace('/', '__')}@{row['commit_sha'][:10]}"
        size = checkout(row["repo_url"], row["commit_sha"], repo_dir)
        total += size
        records = for_project(osv_records(row["cve_id"]), row["metadata"]["language"])
        case = HERE / "cases" / f"{row['task_id']}.json"
        case.write_text(json.dumps(records), encoding="utf-8")
        tasks.append({"adapter": "vulns", "source": f"cases/{case.name}", "goal": owner_repo,
                      "options": {"source_dir": f"repos/{repo_dir.name}"},
                      "expected_noul": {"exploitable": row["ground_truth"] == "exploitable"},
                      "cve": row["cve_id"], "category": row["ground_truth_category"],
                      "language": row["metadata"]["language"], "task_id": row["task_id"],
                      "packages": sorted({a["package"]["name"] for r in records for a in r.get("affected", [])
                                          if a.get("package")})})
        print(f"  {row['task_id'][:60]:<60} {size / 1e6:7.1f} MB  {len(records)} OSV records", flush=True)
    (HERE / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    print(f"{len(tasks)} tasks, checkouts {total / 1e9:.2f} GB")


if __name__ == "__main__":
    sys.exit(main())
