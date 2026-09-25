"""Collect real merged pull requests, with ground truth, for the pr adapter benchmark.

The known answer is where human reviewers left comments. For each merged PR with review comments:
- the diff is taken at the commit the first review round commented on (`original_commit_id`), not the
  final merged diff, so the chunks are the ones the reviewers actually saw
- each top-level comment from someone other than the author (and not a bot) on that commit is mapped to
  the chunk holding its line; those chunks are the expected answer (`expected_choice`, a list of fact IDs,
  any of which is right)

Labels are automatic and marked "review": "auto". Check them before any run, and never change them after.

Needs a GitHub token: set GITHUB_TOKEN in the environment or in .env. The token is never printed or written.

Run: python bench/pr/fetch_prs.py --per-repo 3
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from bench.ci.fetch_runs import GitHub, token  # noqa: E402
from jevbrief.adapters.pr import PrAdapter, parse_diff  # noqa: E402

REPOS = ["pallets/flask", "psf/requests", "encode/httpx", "pydantic/pydantic", "fastapi/fastapi",
         "pytest-dev/pytest", "python-poetry/poetry", "django/django", "vitejs/vite", "prettier/prettier",
         "expressjs/express", "axios/axios", "golang/vscode-go", "cli/cli", "astral-sh/uv"]
BOT = re.compile(r"\[bot\]$|^(dependabot|renovate|github-actions|codecov|copilot|coderabbit)", re.I)
NIT = re.compile(r"^\s*(nit|typo|minor|style)\b|^\s*```suggestion", re.I)
MAX_FILES, MIN_CHUNKS, MAX_CHUNKS = 40, 3, 120


def chunk_for(files: list[dict], c: dict):
    """(path, hunk) holding a review comment's line on the commit it was made on, or None."""
    f = next((f for f in files if f["path"] == c["path"]), None)
    line = c.get("original_line")
    if not f or not line:
        return None
    old = c.get("side") == "LEFT"
    for h in f["hunks"]:
        start, n = (h["old_start"], h["old_len"]) if old else (h["new_start"], h["new_len"])
        if start <= line < start + max(n, 1):
            return f["path"], h
    return None


def collect(gh: GitHub, repo: str, per_repo: int, out: Path) -> list[dict]:
    tasks = []
    pulls = gh.get(f"/repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100") or []
    for pr in pulls:
        if len(tasks) >= per_repo:
            break
        author = pr["user"]["login"]
        if not pr.get("merged_at") or BOT.search(author):
            continue
        n = pr["number"]
        comments = [c for c in gh.get(f"/repos/{repo}/pulls/{n}/comments?per_page=100") or []
                    if not c.get("in_reply_to_id") and c["user"]["login"] != author
                    and not BOT.search(c["user"]["login"]) and c.get("subject_type", "line") == "line"]
        if not comments:
            continue
        first = min(comments, key=lambda c: c["created_at"])["original_commit_id"]
        round1 = [c for c in comments if c["original_commit_id"] == first]
        diff = gh.get(f"/repos/{repo}/compare/{pr['base']['sha']}...{first}", raw=True,
                      accept="application/vnd.github.diff")
        if not diff:
            continue  # force-pushed away
        text = diff.decode("utf-8", "replace")
        files = parse_diff(text)
        chunks = sum(len(f["hunks"]) for f in files)
        if len(files) > MAX_FILES or not MIN_CHUNKS <= chunks <= MAX_CHUNKS:
            continue
        hits: dict[str, dict] = {}
        for c in round1:
            got = chunk_for(files, c)
            if got:
                path, h = got
                fid = _fact_id(path, h)
                hit = hits.setdefault(fid, {"id": fid, "chunk": f"{path}:{h['new_start']}", "comments": []})
                hit["comments"].append({"by": c["user"]["login"], "nit": bool(NIT.search(c["body"])),
                                        "text": " ".join(c["body"].split())[:160], "url": c["html_url"]})
        if not hits:
            continue
        tag = f"{repo.replace('/', '_')}_{n}"
        (out / f"{tag}.diff").write_text(text, encoding="utf-8")
        all_nits = all(cm["nit"] for h in hits.values() for cm in h["comments"])
        tasks.append({"adapter": "pr", "source": f"prs/{tag}.diff", "goal": pr["title"],
                      "expected_choice": sorted(hits), "expected_chunks": list(hits.values()),
                      "chunks": chunks, "files": len(files), "pr": pr["html_url"], "commit": first,
                      "review": "auto" + (": only nit comments" if all_nits else "")})
        print(f"  #{n:<6} {chunks:>3} chunks, {len(hits)} commented{'  (nits only)' if all_nits else ''}  "
              f"{pr['title'][:60]}", flush=True)
    return tasks


def _fact_id(path: str, h: dict) -> str:
    """The pr adapter's ID for this chunk, so labels match what extract() produces."""
    from jevbrief.facts import fact_id
    return fact_id("pr", path, str(h["old_start"]), str(h["new_start"]))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repos", nargs="*", default=REPOS)
    p.add_argument("--per-repo", type=int, default=3)
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    gh = GitHub(token())
    out = HERE / "prs"
    out.mkdir(exist_ok=True)
    tasks_path = HERE / "tasks.json"
    tasks = json.loads(tasks_path.read_text(encoding="utf-8")) if tasks_path.exists() else []
    seen = {t["source"] for t in tasks}
    for repo in args.repos:
        print(repo, flush=True)
        try:
            tasks += [t for t in collect(gh, repo, args.per_repo, out) if t["source"] not in seen]
        except Exception as e:  # one bad repo should not end the run
            print(f"  skipped {repo}: {type(e).__name__}: {e}", flush=True)
        tasks_path.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    ids = {f.id for t in tasks for f in PrAdapter().extract(str(HERE / t["source"])).facts
           if f.id in t["expected_choice"]}
    missing = sum(i not in ids for t in tasks for i in t["expected_choice"])
    print(f"{len(tasks)} tasks, {sum(len(t['expected_choice']) for t in tasks)} labeled chunks"
          f"{f', {missing} not found by the adapter' if missing else ''}")


if __name__ == "__main__":
    main()
