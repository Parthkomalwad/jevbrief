"""Collect real failed GitHub Actions runs, with ground truth, for the ci adapter benchmark.

Two kinds of task, both labeled from what happened next rather than by hand:
- fix: a failed run on the default branch, followed within `--max-fix` commits by a passing run of the
  same workflow. The files changed in between are the fix; the expected answer is the error group that
  names one of them.
- flaky: a run whose first attempt failed and whose rerun on the same commit passed. Nothing changed,
  so the expected flaky answer is "true".

Needs a GitHub token (log downloads require one, even for public repos): set GITHUB_TOKEN in the
environment or in .env. The token is never printed or written.

Run: python bench/ci/fetch_runs.py --per-repo 5
Then review bench/ci/tasks.json: auto-labels marked "review": "auto" are guesses to check.
"""

from __future__ import annotations

import argparse
import http.client
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from jevbrief.adapters.ci import CiAdapter  # noqa: E402

API = "https://api.github.com"
REPOS = ["pallets/flask", "psf/requests", "encode/httpx", "pydantic/pydantic", "tiangolo/fastapi",
         "pytest-dev/pytest", "python-poetry/poetry", "pandas-dev/pandas", "vercel/next.js", "vitejs/vite",
         "prettier/prettier", "expressjs/express", "axios/axios", "rust-lang/rustlings", "golang/vscode-go"]


def token() -> str:
    t = os.environ.get("GITHUB_TOKEN", "")
    env = ROOT / ".env"
    if not t and env.exists():
        m = re.search(r"^GITHUB_TOKEN=(.+)$", env.read_text(encoding="utf-8"), re.M)
        t = m.group(1).strip().strip('"') if m else ""
    if not t:
        sys.exit("Set GITHUB_TOKEN (a fine-grained token with public read access is enough).")
    return t


class GitHub:
    def __init__(self, tok: str):
        self.headers = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "jevbrief-bench"}

    def get(self, path: str, raw: bool = False):
        req = urllib.request.Request(path if path.startswith("http") else API + path, headers=self.headers)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = r.read()
                    return body if raw else json.loads(body)
            except urllib.error.HTTPError as e:
                if e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0":
                    wait = max(int(e.headers.get("X-RateLimit-Reset", time.time() + 60)) - time.time(), 5)
                    print(f"  rate limited, waiting {wait:.0f}s", flush=True)
                    time.sleep(wait)
                elif e.code in (404, 410):  # logs expired or deleted
                    return None
                elif attempt == 2:
                    raise
            except (OSError, http.client.HTTPException) as e:  # dropped connections, timeouts, partial reads
                if attempt == 2:
                    print(f"  giving up on {path}: {type(e).__name__}", flush=True)
                    return None
                time.sleep(2 * (attempt + 1))
        return None


def failed_jobs_zip(gh: GitHub, repo: str, run: dict, attempt: int | None = None) -> bytes | None:
    """The run's log archive, keeping only the failed jobs."""
    base = f"/repos/{repo}/actions/runs/{run['id']}" + (f"/attempts/{attempt}" if attempt else "")
    jobs = gh.get(base + "/jobs?per_page=100") or {}
    failed = {j["name"] for j in jobs.get("jobs", []) if j.get("conclusion") == "failure"}
    data = gh.get(base + "/logs", raw=True)
    if not data or not failed:
        return None
    out = io.BytesIO()
    safe = {re.sub(r"[/:<>|*?\"]", "", n) for n in failed}  # GitHub strips these from folder names
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            folder = name.split("/")[0] if "/" in name else re.sub(r"^\d+_", "", name.rsplit(".", 1)[0])
            if folder in failed or folder in safe:
                dst.writestr(name, src.read(name))
    return out.getvalue() if len(zipfile.ZipFile(out).namelist()) else None


def has_errors(data: bytes) -> bool:
    """Whether the adapter finds any error at all (some failed jobs only run `false` to report others)."""
    tmp = HERE / "runs" / ".check.zip"
    tmp.write_bytes(data)
    try:
        a = CiAdapter()
        return any(f.kept for f in a.rules().apply(a.extract(tmp).facts, "", [], {}))
    except ValueError:
        return False
    finally:
        tmp.unlink()


def label(path: Path, changed: list[str]) -> tuple[str | None, list[str]]:
    """The first kept error group that names a changed file or test, as `expected_contains`."""
    a = CiAdapter()
    try:
        facts = a.extract(path).facts
    except ValueError:
        return None, []
    rules = a.rules()
    facts = rules.apply(facts, "", [], {})
    keys = {}
    for f in changed:
        stem = Path(f).stem
        if len(stem) >= 4 and stem not in ("index", "main", "utils", "setup", "__init__"):
            keys[stem.lower()] = stem
    hits = []
    for fact in facts:
        text = f"{fact.label} {fact.meta.get('template', '')}".lower()
        hits += [keys[k] for k in keys if k in text and fact.kept]
    return (max(hits, key=len) if hits else None), sorted(set(hits))  # the most specific name


def collect(gh: GitHub, repo: str, per_repo: int, max_fix: int, out: Path) -> list[dict]:
    info = gh.get(f"/repos/{repo}") or {}
    branch = info.get("default_branch", "main")
    runs = (gh.get(f"/repos/{repo}/actions/runs?branch={branch}&event=push&status=completed&per_page=100") or {})
    runs = sorted(runs.get("workflow_runs", []), key=lambda r: r["created_at"])
    tasks, fixes, flakies = [], 0, 0
    for i, run in enumerate(runs):
        if fixes >= per_repo and flakies >= per_repo:
            break
        tag = f"{repo.replace('/', '_')}_{run['id']}"
        # flaky: first attempt failed, a rerun on the same commit passed
        if run["conclusion"] == "success" and run.get("run_attempt", 1) > 1 and flakies < per_repo:
            first = gh.get(f"/repos/{repo}/actions/runs/{run['id']}/attempts/1") or {}
            if first.get("conclusion") == "failure":
                data = failed_jobs_zip(gh, repo, run, attempt=1)
                if data and has_errors(data):
                    (out / f"{tag}_a1.zip").write_bytes(data)
                    flakies += 1
                    tasks.append({"adapter": "ci", "source": f"runs/{tag}_a1.zip", "kind": "flaky", "flaky": True,
                                  "goal": f"The {run['name']} workflow failed on {repo}",
                                  "run": run["html_url"] + "/attempts/1", "review": "auto"})
                    print(f"  flaky  {run['html_url']}", flush=True)
            continue
        # fix: failed, then the same workflow passes within a few commits
        if run["conclusion"] != "failure" or fixes >= per_repo:
            continue
        nxt = next((r for r in runs[i + 1:] if r["workflow_id"] == run["workflow_id"]), None)
        if not nxt or nxt["conclusion"] != "success" or nxt["head_sha"] == run["head_sha"]:
            continue
        cmp = gh.get(f"/repos/{repo}/compare/{run['head_sha']}...{nxt['head_sha']}") or {}
        if not cmp or cmp.get("ahead_by", 99) > max_fix:
            continue
        changed = [f["filename"] for f in cmp.get("files", [])]
        data = failed_jobs_zip(gh, repo, run)
        if not data or not has_errors(data):
            continue
        path = out / f"{tag}.zip"
        path.write_bytes(data)
        expected, candidates = label(path, changed)
        fixes += 1
        tasks.append({"adapter": "ci", "source": f"runs/{tag}.zip", "kind": "fix", "flaky": False,
                      "goal": f"The {run['name']} workflow failed on {repo}",
                      **({"expected_contains": expected} if expected else {}),
                      "candidates": candidates, "fix_files": changed[:30], "run": run["html_url"],
                      "fix": cmp.get("html_url"), "review": "auto" if expected else "needs label: fix names no error, maybe flaky"})
        print(f"  fix    {run['html_url']}  -> {expected or '(needs label)'}", flush=True)
    return tasks


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repos", nargs="*", default=REPOS)
    p.add_argument("--per-repo", type=int, default=5, help="max fix tasks and max flaky tasks per repo")
    p.add_argument("--max-fix", type=int, default=3, help="max commits between the failure and the fix")
    args = p.parse_args()
    gh = GitHub(token())
    out = HERE / "runs"
    out.mkdir(exist_ok=True)
    tasks_path = HERE / "tasks.json"
    tasks = json.loads(tasks_path.read_text(encoding="utf-8")) if tasks_path.exists() else []
    seen = {t["source"] for t in tasks}
    for repo in args.repos:
        print(repo, flush=True)
        try:
            tasks += [t for t in collect(gh, repo, args.per_repo, args.max_fix, out) if t["source"] not in seen]
        except Exception as e:  # one bad repo should not end the run
            print(f"  skipped {repo}: {type(e).__name__}: {e}", flush=True)
        tasks_path.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    fix = [t for t in tasks if t["kind"] == "fix"]
    print(f"{len(tasks)} tasks: {len(fix)} fix ({sum('expected_contains' in t for t in fix)} auto-labeled), "
          f"{len(tasks) - len(fix)} flaky")


if __name__ == "__main__":
    main()
