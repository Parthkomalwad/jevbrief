"""The ci adapter: CI build logs and JUnit test results to failure facts, for finding why a build broke.

Reads any mix of:
- `gh run view <id> --log` or `--log-failed` output (`job<TAB>step<TAB>time line`)
- the logs zip from GitHub Actions ("Download log archive"), unzipped or not (`job/<n>_<step>.txt`)
- plain log files (the file name becomes the job)
- JUnit XML reports (pytest `--junitxml`, Maven Surefire, Jest, Go's gotestsum, ...)

Pass a path (file, zip, or directory) or a list of paths. Standard library only.

Error lines are grouped by job, step, and message template. Where a group sits relative to the
failing step, and whether it looks flaky, are computed here and sent to Jev as words.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

from ...briefing import Extracted
from ...facts import Fact, clean_label, fact_id, register_reasons
from ...questions import FactChoice
from ...rules import CORE_RULES, Boost, Drop, Rule, RuleSet
from .. import Adapter
from ..otel import frequency, template

BELOW_SEVERITY = "ci.below_severity"
SUMMARY_LINE = "ci.summary_line"
PASSED_STEP = "ci.passed_step"
AFTER_FAILURE = "ci.after_failure"
PASSED_ON_RERUN = "ci.passed_on_rerun"
REASONS = {
    BELOW_SEVERITY: "Less severe than the minimum severity (default: errors only)",
    SUMMARY_LINE: "Generic exit-code or test-count summary line, a symptom of an earlier error",
    PASSED_STEP: "Error-looking output in a step that did not fail",
    AFTER_FAILURE: "Output from a step that ran after the failing step (cleanup or follow-on)",
    PASSED_ON_RERUN: "Test failed, then passed on a rerun, so it did not break the build",
    "ci.test_failure": "Kept: a failed test from a JUnit report",
    "ci.failed_step": "Kept: output from the failing step",
    "ci.first_error": "Kept: the first error in its failing step",
}

SEV = {"warning": 13, "error": 17}
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
TS = re.compile(r"^\ufeff?(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z) ?")
MARKER = re.compile(r"^##\[(error|warning)\]")
FAIL_MARKER = re.compile(r"^##\[error\]", re.I)
ERROR = re.compile(r"\b(errors?|failed|failure|fatal|exception|traceback|panic|segmentation fault)\b|\w+(Error|Exception):"
                   r"|npm ERR!|^E {2,}|^FAILED\b", re.I)
NOT_ERROR = re.compile(r"\b(0|no) (errors?|failures?|failed)\b|\berror[_-]?(handling|handler|page)s?\b|-Werror"
                       r"|continue-on-error|fail-fast", re.I)
WARNING = re.compile(r"\bwarn(ing)?s?\b|\bdeprecat", re.I)
SUMMARY = re.compile(r"process completed with exit code|exited with (exit )?(code|status)|^make: \*\*\*"
                     r"|^=+ .*\b\d+ (failed|errors?)\b.* in [\d.]+s|^Tests?:? .*\d+ failed|^FAIL\s*$"
                     r"|^error: command .* failed with exit|^Error: The operation was canceled", re.I)
FLAKY = re.compile(r"timed? ?out|timeout|connection (reset|refused|closed)|ECONNRESET|ETIMEDOUT|EAI_AGAIN"
                   r"|temporary failure in name resolution|could not resolve host|rate limit|too many requests"
                   r"|\b50[234]\b|runner .*(lost|shut ?down)|lost communication with the server"
                   r"|no space left on device|out of memory|\bOOM\b|flaky|intermittent", re.I)
SKIP_LINE = re.compile(r"^##\[(group|endgroup|command|debug)\]|^\[command\]|^shell: |^\s*$")
RERUN_TAGS = ("flakyFailure", "flakyError", "rerunFailure", "rerunError")


def classify(line: str) -> str | None:
    """"error", "warning", or None for a log line (after the timestamp is removed)."""
    m = MARKER.match(line)
    if m:
        return m.group(1)
    if NOT_ERROR.search(line) and not ERROR.search(NOT_ERROR.sub("", line)):
        return None
    if ERROR.search(line):
        return "error"
    return "warning" if WARNING.search(line) else None


def _step(name: str) -> tuple[int, str]:
    """'3_Run tests.txt' -> (3, 'Run tests')."""
    stem = name.rsplit(".", 1)[0]
    n, _, rest = stem.partition("_")
    return (int(n), rest) if n.isdigit() and rest else (0, stem)


def _lines(text: str, job: str | None, step: str | None, step_n: int):
    """Yield (job, step, step_n, line). Without a job, the text is `gh run view --log` output."""
    steps: dict[tuple, int] = {}
    for raw in text.splitlines():
        if job is None:
            parts = raw.split("\t", 2)
            if len(parts) < 3:
                continue
            j, s, line = parts
            n = steps.setdefault((j, s), len([k for k in steps if k[0] == j]) + 1)
            yield j, s, n, line
        else:
            yield job, step, step_n, raw


def _log_sources(path: Path):
    """Yield (text, job, step, step_n) for each log in a file, zip, or directory."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(".txt")]
            jobs_with_steps = {n.split("/")[0] for n in names if "/" in n}
            for name in sorted(names):
                job, _, file = name.rpartition("/")
                if not job and _step(file)[1] in jobs_with_steps:
                    continue  # the whole-job log duplicates its per-step logs
                text = z.read(name).decode("utf-8", "replace")
                yield (text, job, *reversed(_step(file))) if job else (text, _step(file)[1], "log", 0)
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    if first.count("\t") >= 2 and TS.match(first.split("\t", 2)[2]):
        yield text, None, None, 0
    elif path.parent.name and _step(path.name)[0]:  # a per-step file from an unzipped archive
        yield text, path.parent.name, _step(path.name)[1], _step(path.name)[0]
    else:
        yield text, path.stem, "log", 0


def _files(source) -> list[Path]:
    paths = source if isinstance(source, (list, tuple)) else [source]
    out = []
    for p in map(Path, paths):
        if p.is_dir():
            files = [f for f in sorted(p.rglob("*")) if f.suffix in (".txt", ".log", ".xml", ".zip")]
            jobs_with_steps = {f.parent.name for f in files if f.parent != p}
            out += [f for f in files if not (f.parent == p and _step(f.name)[1] in jobs_with_steps)]
        else:
            out.append(p)
    return out


def log_records(source) -> list[dict]:
    """Flat log lines: dicts with job, step, step_n, ts, line, level."""
    recs = []
    for path in _files(source):
        if path.suffix == ".xml":
            continue
        for text, job, step, step_n in _log_sources(path):
            for j, s, n, raw in _lines(text, job, step, step_n):
                raw = ANSI.sub("", raw)
                m = TS.match(raw)
                line = raw[m.end():] if m else raw
                if SKIP_LINE.match(line):
                    continue
                recs.append({"job": j, "step": s, "step_n": n, "ts": m.group(1) if m else "",
                             "line": line.rstrip(), "level": classify(line), "i": len(recs)})
    return recs


def junit_cases(source) -> list[dict]:
    """Failed and rerun test cases from JUnit XML files."""
    cases = []
    for path in _files(source):
        if path.suffix != ".xml":
            continue
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        for tc in root.iter("testcase"):
            fails = [c for c in tc if c.tag in ("failure", "error")]
            reruns = [c for c in tc if c.tag in RERUN_TAGS]
            if not fails and not reruns:
                continue
            node = (fails or reruns)[0]
            text = (node.get("message") or "").strip() or next(
                (ln.strip() for ln in (node.text or "").splitlines() if ln.strip()), "")
            cases.append({"suite": path.stem, "classname": tc.get("classname", ""), "name": tc.get("name", ""),
                          "type": node.get("type", "") or node.tag, "message": text, "details": (node.text or "")[:2000],
                          "failed": bool(fails), "reruns": len(reruns)})
    return cases


def _failing_steps(recs: list[dict]) -> dict[str, int]:
    """Job -> step number of its first step with a `##[error]` marker (GitHub's step failure annotation)."""
    out: dict[str, int] = {}
    for r in recs:
        if FAIL_MARKER.match(r["line"]) and r["step_n"]:
            out[r["job"]] = min(out.get(r["job"], r["step_n"]), r["step_n"])
    return out


class CiAdapter(Adapter):
    """Options (dict or keyword arguments to `extract`):

    min_severity  "error" (default) or "warning"
    """

    name = "ci"
    version = "1"
    renderer = "table"
    extra = "ci"
    reasons = REASONS

    def __init__(self, config=None):
        register_reasons(REASONS)
        self.config: dict = dict(config or {})
        self._tail: list[dict] = []  # the last log lines of the most recent extraction, for `raw`

    def configure(self, config) -> None:
        self.config = dict(config or {})

    def extract(self, source, **options) -> Extracted:
        c = {**self.config, **options}
        recs = log_records(source)
        cases = junit_cases(source)
        if not any(r["level"] for r in recs) and not cases:
            raise ValueError("no errors, warnings, or failed tests found. Expected CI logs or JUnit XML")
        failing = _failing_steps(recs)
        self._tail = recs[-254:]

        groups: dict[tuple, list] = {}
        for r in recs:
            if r["level"]:
                text = MARKER.sub("", r["line"]).strip()
                groups.setdefault((r["job"], r["step"], r["level"], template(text)), []).append({**r, "text": text})

        facts = []
        first_in_step: set[tuple] = set()
        for (job, step, level, tmpl), rs in sorted(groups.items(), key=lambda kv: kv[1][0]["i"]):
            n, fail_n = rs[0]["step_n"], failing.get(job)
            summary = bool(SUMMARY.search(rs[0]["text"]))
            where = ("unknown" if fail_n is None else "in the failing step" if n == fail_n else
                     "before the failing step" if n < fail_n else "after the failing step")
            first = where == "in the failing step" and level == "error" and (job, step) not in first_in_step \
                and not summary and not FAIL_MARKER.match(rs[0]["line"])
            if first:
                first_in_step.add((job, step))
            attrs = {"job": job, "step": step, "severity": level, "frequency": frequency(len(rs)), "where": where,
                     "looks_flaky": "yes" if FLAKY.search(tmpl) else "no"}
            if len(tmpl) > 70:
                attrs["message"] = tmpl[:200]
            facts.append(Fact(
                id=fact_id("ci", job, step, level, tmpl), kind=f"{level} line",
                label=clean_label(f"{step}: {tmpl}"), attrs=attrs,
                meta={"sev": SEV[level], "template": tmpl, "order": len(facts), "summary": summary,
                      "first": first, "test": False, "rerun_passed": False, "records": rs[-100:]},
            ))

        for tc in cases:
            test = f"{tc['classname']}.{tc['name']}".strip(".")
            msg = template(tc["message"]) or tc["type"]
            flaky = tc["reruns"] > 0 or bool(FLAKY.search(tc["message"] + " " + tc["type"]))
            attrs = {"test": test, "error_type": tc["type"], "looks_flaky": "yes" if flaky else "no",
                     "result": "failed" if tc["failed"] else "passed on rerun"}
            if len(msg) > 70:
                attrs["message"] = msg[:200]
            facts.append(Fact(
                id=fact_id("ci-test", tc["suite"], test), kind="failed test",
                label=clean_label(f"{tc['name'] or test}: {msg}"), attrs=attrs,
                meta={"sev": SEV["error"], "template": msg, "order": len(facts), "summary": False, "first": False,
                      "test": True, "rerun_passed": not tc["failed"],
                      "records": [{"line": f"{test}: {tc['message']}", "i": 0}, {"line": tc["details"], "i": 1}]},
            ))

        levels = Counter(r["level"] for r in recs if r["level"])
        name = source if isinstance(source, (str, Path)) else "ci logs"
        info = {"name": Path(name).name if isinstance(name, (str, Path)) else name, "lines": len(recs),
                "errors": levels["error"], "failed_tests": sum(tc["failed"] for tc in cases),
                "failing_steps": {j: next(r["step"] for r in recs if r["job"] == j and r["step_n"] == n)
                                  for j, n in failing.items()}}
        return Extracted(facts, info)

    def rules(self) -> RuleSet:
        hidden, disabled, unlabeled, goal_match, duplicate = CORE_RULES
        min_sev = SEV.get(str(self.config.get("min_severity", "error")).lower(), SEV["error"])
        return RuleSet([
            hidden, disabled, unlabeled,
            Rule(BELOW_SEVERITY, lambda f, ctx: Drop(BELOW_SEVERITY) if f.meta["sev"] < min_sev else None),
            Rule(PASSED_ON_RERUN, lambda f, ctx: Drop(PASSED_ON_RERUN) if f.meta["rerun_passed"] else None),
            Rule(SUMMARY_LINE, lambda f, ctx: Drop(SUMMARY_LINE) if f.meta["summary"] else None),
            Rule(PASSED_STEP, lambda f, ctx: Drop(PASSED_STEP) if f.attrs.get("where") == "before the failing step" else None),
            Rule(AFTER_FAILURE, lambda f, ctx: Drop(AFTER_FAILURE) if f.attrs.get("where") == "after the failing step" else None),
            goal_match,
            Rule("ci.test_failure", lambda f, ctx: Boost(0.15, "ci.test_failure") if f.meta["test"] else None),
            Rule("ci.first_error", lambda f, ctx: Boost(0.1, "ci.first_error") if f.meta["first"] else None),
            Rule("ci.failed_step", lambda f, ctx: Boost(0.15, "ci.failed_step")
                 if f.attrs.get("where") == "in the failing step" else None),
            duplicate,
        ])

    def packs(self):
        pack = FactChoice(
            "likely_cause",
            "Build failure: {goal}\n"
            "Each item in `failures` is either a group of similar error lines from one CI step, or a failed test. "
            "Which one item most likely shows the root cause of the failure, rather than a symptom or a follow-on error?",
            lambda f: f"{f.label} ({f.kind}, {f.attrs.get('where', f.attrs.get('result', ''))}, "
                      f"flaky-looking: {f.attrs.get('looks_flaky')})",
            none_text="None of these explains the build failure",
            extra={"flaky": {"type": "noul", "instructions":
                             "Build failure: {goal}\nDoes this failure look flaky, caused by timing, the network, or "
                             "the CI machine, rather than by a change in the code?",
                             "criteria": {"true": "Flaky: rerunning would likely pass",
                                          "false": "A real failure caused by the code or config"}}},
        )
        return {pack.name: pack}

    def state(self, goal, kept, source):
        return {"build": goal, "failures": [f.state() for f in kept]}

    def raw(self, facts):
        """What a naive integration sends: the last log lines of the run, one fact each."""
        return [Fact(id=fact_id("ci-raw", str(r["i"]), r["line"]), kind=r["level"] or "line",
                     label=clean_label(f"{r['step']}: {r['line']}"), attrs={"job": r["job"]},
                     meta={"order": k, "template": template(r["line"])})
                for k, r in enumerate(self._tail)]
