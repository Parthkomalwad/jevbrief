"""The pr adapter: a pull request's diff to chunk facts, for finding what most needs a human reviewer.

Reads any mix of:
- unified diffs: `gh pr diff <n>` output, `git diff`, or a `.diff` file
- `git format-patch` / GitHub `.patch` files (the mail headers are skipped)
- the PR's JSON from the GitHub API: `/pulls/{n}/files` (a list with a `patch` per file),
  and optionally `/pulls/{n}` (title, body, size) for context
- a folder holding any of these

Pass a path, a list of paths, or the diff text itself. Standard library only.

Each diff chunk (hunk) is one fact. The file's role, the chunk's size and change kind, whether a
matching test changed, and what the chunk touches are computed here and sent to Jev as words.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from ...briefing import Extracted
from ...facts import Fact, clean_label, fact_id
from ...questions import FactChoice
from ...rules import Boost, Drop, Rule, RuleSet, disabled, duplicate, goal_match, hidden, unlabeled
from ...sources import find_files
from .. import Adapter

GENERATED = "pr.generated"
VENDORED = "pr.vendored"
RENAME_ONLY = "pr.rename_only"
FORMATTING_ONLY = "pr.formatting_only"
DOCS_ONLY = "pr.docs_only"
RISKY_AREA = "pr.risky_area"
NO_TEST = "pr.no_test"
REASONS = {
    GENERATED: "Generated file or lockfile, not written by hand",
    VENDORED: "Vendored third-party code",
    RENAME_ONLY: "File renamed or moved with no other change",
    FORMATTING_ONLY: "Only whitespace or line breaks changed",
    DOCS_ONLY: "Documentation only (dropped when drop_docs is set)",
    RISKY_AREA: "Kept: touches auth or security, SQL, concurrency, or a public API",
    NO_TEST: "Kept: a source change with no matching test change",
}

LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "cargo.lock", "go.sum",
             "gemfile.lock", "composer.lock", "uv.lock", "pipfile.lock", "podfile.lock", "flake.lock",
             "packages.lock.json", "npm-shrinkwrap.json", "bun.lockb", "mix.lock", "pubspec.lock"}
GENERATED_PATH = re.compile(r"(\.min\.(js|css)|\.pb\.go|_pb2(_grpc)?\.pyi?|\.pb\.(h|cc)|\.g\.dart|\.generated\.\w+"
                            r"|\.designer\.cs|\.snap|\.map)$|(^|/)(__snapshots__|generated)/", re.I)
GENERATED_MARK = re.compile(r"@generated|Code generated .* DO NOT EDIT|auto-?generated|do not edit", re.I)
VENDOR_PATH = re.compile(r"(^|/)(vendor|third_party|thirdparty|3rdparty|node_modules|external|extern|deps)/", re.I)
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|specs|testing)/|(^|/)test_[^/]+$|_tests?\.\w+$"
                       r"|\.(test|spec)\.\w+$|Tests?\.(java|kt|cs|swift)$", re.I)
DOCS_PATH = re.compile(r"\.(md|mdx|rst|adoc|txt)$|(^|/)(docs?|documentation)/|(^|/)(changelog|changes|authors"
                       r"|contributing|license|notice|readme)[^/]*$", re.I)
CONFIG_PATH = re.compile(r"\.(ya?ml|toml|ini|cfg|conf|json|xml|properties|env\.example|gradle|lock)$"
                         r"|(^|/)(dockerfile|makefile|\.github/|\.gitignore|\.editorconfig|setup\.py$|pyproject)", re.I)

TOUCHES = {
    "auth or security": re.compile(r"\b(auth\w*|login|password|passwd|secret|token|credential|permission|privilege"
                                   r"|role|csrf|xss|cors|jwt|oauth|session|cookie|crypt\w*|hash\w*|signature|sanitiz\w*"
                                   r"|escape|verify|certificate|tls|ssl|acl|admin)\b", re.I),
    "SQL": re.compile(r"\b(select\s+.+\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from|create\s+table"
                      r"|alter\s+table|drop\s+table|join\s+\w+\s+on)\b|\.(execute|executemany|raw|query)\(|\bmigrations?\b",
                      re.I),
    "concurrency": re.compile(r"\b(thread\w*|mutex|rwlock|lock\(\)|locks?|semaphore|atomic\w*|async|await|goroutine"
                              r"|go func|chan\b|channel|synchronized|volatile|race|deadlock|concurrent\w*|executor"
                              r"|futures?|promise\.all|asyncio)\b", re.I),
    "error handling": re.compile(r"\b(try|except|catch|finally|raise|throw|throws|panic|recover|rescue)\b"
                                 r"|if err != nil|\.unwrap\(\)|\?;\s*$", re.I),
}
PUBLIC_API = re.compile(r"^\s*(export\s|pub\s+(fn|struct|enum|trait|mod|const)|public\s|def\s+[a-zA-Z]\w*\s*\("
                        r"|class\s+[A-Z]\w*|func\s+(\([^)]*\)\s*)?[A-Z]\w*\s*\(|interface\s+\w+|@app\.(route|get|post)"
                        r"|@router\.)")
RISKY = ("auth or security", "SQL", "concurrency", "public API")

DIFF_GIT = re.compile(r"^diff --git (?:\"?a/(.+?)\"? \"?b/(.+?)\"?)$")
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


def _strip_prefix(p: str) -> str | None:
    p = p.split("\t")[0].strip().strip('"')
    if p == "/dev/null":
        return None
    return p[2:] if p[:2] in ("a/", "b/") else p


def parse_diff(text: str) -> list[dict]:
    """Files from a unified diff: dicts with path, old_path, status, binary, similarity, hunks.

    Each hunk is a dict with old_start, old_len, new_start, new_len, section, and lines
    (a list of (tag, text), tag in "+", "-", " ").
    """
    files: list[dict] = []
    cur: dict | None = None
    hunk: dict | None = None

    def new_file(path, old_path):
        nonlocal cur, hunk
        cur = {"path": path, "old_path": old_path, "status": "modified", "binary": False, "similarity": None,
               "hunks": []}
        hunk = None
        files.append(cur)

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if hunk is not None and hunk["left"] > 0 and line[:1] in ("+", "-", " ", ""):
            tag = line[:1] or " "
            hunk["lines"].append((tag, line[1:]))
            if tag in "- ":
                hunk["old_left"] -= 1
            if tag in "+ ":
                hunk["new_left"] -= 1
            hunk["left"] = max(hunk["old_left"], hunk["new_left"])
            continue
        if line.startswith("\\"):  # "\ No newline at end of file"
            continue
        m = DIFF_GIT.match(line)
        if m:
            new_file(m.group(2), m.group(1))
            continue
        header = line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")
        if header and (cur is None or cur["hunks"]):
            new_file(None, None)  # a plain diff with no `diff --git` line
        if cur is None:
            continue  # mail headers and the commit message of a .patch file
        if header:
            old = _strip_prefix(line[4:])
            cur["old_path"] = old
            if old is None:
                cur["status"] = "added"
        elif line.startswith("+++ "):
            new = _strip_prefix(line[4:])
            if new is None:
                cur["status"] = "removed"
            else:
                cur["path"] = new
        elif line.startswith("new file mode"):
            cur["status"] = "added"
        elif line.startswith("deleted file mode"):
            cur["status"] = "removed"
        elif line.startswith("rename from "):
            cur["old_path"], cur["status"] = line[12:], "renamed"
        elif line.startswith("rename to "):
            cur["path"], cur["status"] = line[10:], "renamed"
        elif line.startswith("similarity index "):
            cur["similarity"] = int(line[17:].rstrip("%") or 0)
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            cur["binary"] = True
        else:
            m = HUNK.match(line)
            if m:
                o_len = int(m.group(2)) if m.group(2) is not None else 1
                n_len = int(m.group(4)) if m.group(4) is not None else 1
                hunk = {"old_start": int(m.group(1)), "old_len": o_len, "new_start": int(m.group(3)),
                        "new_len": n_len, "section": m.group(5).strip(), "lines": [],
                        "old_left": o_len, "new_left": n_len, "left": max(o_len, n_len)}
                cur["hunks"].append(hunk)
            elif line.startswith("-- ") and hunk is not None:
                hunk = None  # the signature line that ends a format-patch mail
    for f in files:
        f["path"] = f["path"] or f["old_path"]
        f["old_path"] = f["old_path"] or f["path"]
        for h in f["hunks"]:
            for k in ("old_left", "new_left", "left"):
                h.pop(k)
    return [f for f in files if f["path"]]


def _from_api_files(items: list[dict]) -> list[dict]:
    """Files from GitHub's `/pulls/{n}/files` JSON, whose `patch` holds only the hunks."""
    status = {"added": "added", "removed": "removed", "renamed": "renamed", "copied": "added"}
    files = []
    for it in items:
        path, old = it["filename"], it.get("previous_filename") or it["filename"]
        parsed = parse_diff(f"diff --git a/{old} b/{path}\n--- a/{old}\n+++ b/{path}\n{it.get('patch') or ''}")
        f = parsed[0] if parsed else {"path": path, "old_path": old, "hunks": []}
        f.update(path=path, old_path=old, status=status.get(str(it.get("status")), "modified"),
                 binary="patch" not in it and it.get("changes", 0) > 0,
                 similarity=100 if it.get("status") == "renamed" and not it.get("changes") else None)
        files.append(f)
    return files


def _read(source) -> tuple[list[dict], dict]:
    """(files, pr) from a path, a list of paths, or diff text."""
    if isinstance(source, str) and "\n" in source:
        return parse_diff(source), {}
    files: list[dict] = []
    pr: dict = {}
    for path in find_files(source, (".diff", ".patch", ".json")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".json":
            data = json.loads(text)
            if isinstance(data, list) and data and isinstance(data[0], dict) and "filename" in data[0]:
                files += _from_api_files(data)
            elif isinstance(data, dict) and ("title" in data or "number" in data):
                pr = data
        else:
            files += parse_diff(text)
    # The same file from a diff and from the API JSON: keep the first.
    seen: set[str] = set()
    out = []
    for file in files:
        if file["path"] not in seen:
            seen.add(file["path"])
            out.append(file)
    return out, pr


def role(path: str, first_lines: str = "") -> str:
    """source, test, config, docs, generated, lockfile, or vendored."""
    name = PurePosixPath(path).name.lower()
    if name in LOCKFILES:
        return "lockfile"
    if VENDOR_PATH.search(path):
        return "vendored"
    if GENERATED_PATH.search(path) or GENERATED_MARK.search(first_lines):
        return "generated"
    if TEST_PATH.search(path):
        return "test"
    if DOCS_PATH.search(path):
        return "docs"
    if CONFIG_PATH.search(path):
        return "config"
    return "source"


def _stem(path: str) -> str:
    """'src/pay/refund.py' and 'tests/test_refund.py' and 'refund.spec.ts' -> 'refund'."""
    s = PurePosixPath(path).name.split(".")[0].lower()
    s = re.sub(r"^tests?_|_tests?$|tests?$|_spec$", "", s)
    return s


def size(n: int) -> str:
    return "small" if n <= 5 else "medium" if n <= 30 else "large"


def _squash(lines: list[str]) -> str:
    return "".join("".join(lines).split())


def touches(lines: list[str]) -> list[str]:
    out = [name for name, rx in TOUCHES.items() if any(rx.search(ln) for ln in lines)]
    if any(PUBLIC_API.match(ln) for ln in lines):
        out.insert(0, "public API")
    return out


class PrAdapter(Adapter):
    """Options (dict or keyword arguments to `extract`):

    drop_docs  drop documentation chunks (default False)
    """

    name = "pr"
    version = "1"
    renderer = "table"
    extra = "pr"
    reasons = REASONS

    def extract(self, source, **options) -> Extracted:
        files, pr = _read(source)
        if not files:
            raise ValueError("no diff found. Expected `gh pr diff` output, a .diff or .patch file, "
                             "or /pulls/{n}/files JSON")
        tested = {_stem(f["path"]) for f in files if role(f["path"]) == "test"}

        facts: list[Fact] = []
        for f in files:
            path = f["path"]
            head = "\n".join(t for h in f["hunks"][:1] for _, t in h["lines"][:8])
            r = role(path, head)
            base = {"file": path, "role": r}
            if f["old_path"] != path:
                base["renamed_from"] = f["old_path"]
            test = "yes" if _stem(path) in tested else "no"
            if not f["hunks"]:
                kind = "renamed file" if f["status"] == "renamed" else "binary file" if f["binary"] else "file"
                facts.append(Fact(
                    id=fact_id("pr", path, "file"), kind=kind, label=clean_label(f"{path} ({f['status']})"),
                    attrs={**base, "change": f["status"]},
                    meta={"order": len(facts), "role": r, "rename_only": f["status"] == "renamed",
                          "formatting": False, "touches": [], "test": test, "hunk": None, "path": path}))
                continue
            for h in f["hunks"]:
                plus = [t for tag, t in h["lines"] if tag == "+"]
                minus = [t for tag, t in h["lines"] if tag == "-"]
                change = ("added" if plus and not minus else "removed" if minus and not plus else "modified")
                formatting = bool(plus and minus) and _squash(plus) == _squash(minus)
                tch = touches(plus + minus)
                attrs = {**base, "lines": f"{h['new_start']}-{h['new_start'] + max(h['new_len'] - 1, 0)}",
                         "size": size(len(plus) + len(minus)), "change": change}
                if h["section"]:
                    attrs["in"] = h["section"][:80]
                if r == "source":
                    attrs["matching_test_changed"] = test
                if tch:
                    attrs["touches"] = ", ".join(tch)
                excerpt = " | ".join(ln.strip() for ln in (plus or minus) if ln.strip())
                if excerpt:
                    attrs["excerpt"] = excerpt[:160]
                first = next((ln.strip() for ln in plus + minus if ln.strip()), "")
                facts.append(Fact(
                    id=fact_id("pr", path, str(h["old_start"]), str(h["new_start"])), kind=f"{change} chunk",
                    label=clean_label(f"{path}:{h['new_start']} {h['section'] or first}"), attrs=attrs,
                    meta={"order": len(facts), "role": r, "rename_only": False, "formatting": formatting,
                          "touches": tch, "test": test, "hunk": h, "path": path}))

        info = {"name": pr.get("title") or (Path(source).name if isinstance(source, (str, Path))
                                           and "\n" not in str(source) else "pull request"),
                "files": len(files), "chunks": sum(len(f["hunks"]) for f in files),
                "added": sum(t == "+" for f in files for h in f["hunks"] for t, _ in h["lines"]),
                "removed": sum(t == "-" for f in files for h in f["hunks"] for t, _ in h["lines"])}
        if pr.get("number"):
            info["number"] = pr["number"]
        return Extracted(facts, info)

    def rules(self, options: dict | None = None) -> RuleSet:
        drop_docs = bool(self.settings(options).get("drop_docs", False))
        return RuleSet([
            hidden, disabled, unlabeled,
            Rule(GENERATED, lambda f, ctx: Drop(GENERATED) if f.meta["role"] in ("generated", "lockfile") else None),
            Rule(VENDORED, lambda f, ctx: Drop(VENDORED) if f.meta["role"] == "vendored" else None),
            Rule(RENAME_ONLY, lambda f, ctx: Drop(RENAME_ONLY) if f.meta["rename_only"] else None),
            Rule(FORMATTING_ONLY, lambda f, ctx: Drop(FORMATTING_ONLY) if f.meta["formatting"] else None),
            Rule(DOCS_ONLY, lambda f, ctx: Drop(DOCS_ONLY) if drop_docs and f.meta["role"] == "docs" else None),
            goal_match,
            Rule(RISKY_AREA, lambda f, ctx: Boost(0.2, RISKY_AREA)
                 if any(t in RISKY for t in f.meta["touches"]) else None),
            Rule(NO_TEST, lambda f, ctx: Boost(0.1, NO_TEST)
                 if f.meta["role"] == "source" and f.meta["test"] == "no" else None),
            duplicate,
        ])

    def packs(self):
        pack = FactChoice(
            "needs_review",
            "Pull request: {goal}\n"
            "Each item in `chunks` is one changed part of the pull request's diff. Which one chunk most needs a "
            "careful human reviewer, because it is the most likely to hide a bug, a security problem, or a design "
            "issue?",
            lambda f: f"{f.label} ({f.attrs.get('role')}, {f.attrs.get('size', '')} {f.attrs.get('change')}"
                      f"{', touches ' + f.attrs['touches'] if f.attrs.get('touches') else ''})",
            none_text="None of these needs careful review",
            extra={"safe_to_merge": {"type": "noul", "instructions":
                                     "Pull request: {goal}\nIs this pull request safe to merge without changes?",
                                     "criteria": {"true": "Safe to merge as it is",
                                                  "false": "Needs changes or a closer look before merging"}}},
        )
        return {pack.name: pack}

    def state(self, goal, kept, source):
        return {"pull_request": goal, "chunks": [f.state() for f in kept]}

    def raw(self, facts):
        """What a naive integration sends: the full diff, one fact per chunk with its text."""
        out = []
        for f in facts:
            h = f.meta.get("hunk")
            body = "\n".join(tag + t for tag, t in h["lines"]) if h else f.attrs.get("change", "")
            out.append(Fact(id=f.id, kind="chunk", label=clean_label(f.label), attrs={"diff": body[:4000]},
                            meta={"order": f.meta["order"], "path": f.meta["path"]}))
        return out
