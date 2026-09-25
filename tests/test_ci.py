import zipfile

from jevbrief import Briefing
from jevbrief.adapters.ci import CiAdapter, classify
from jevbrief.testing import FakeJev, check_adapter

T = "2026-09-25T10:00:{:02d}.0000000Z"


def gh_log(*rows):
    """`gh run view --log` lines from (job, step, line) rows."""
    return "\n".join(f"{j}\t{s}\t{T.format(i % 60)} {line}" for i, (j, s, line) in enumerate(rows)) + "\n"


LOG = gh_log(
    ("test", "Set up job", "Current runner version: '2.319.1'"),
    ("test", "Install", "npm WARN deprecated inflight@1.0.6: This module is not supported"),
    ("test", "Install", "found 0 errors in 212 packages"),
    ("test", "Lint", "src/api.py:3: error: unused import (continue-on-error step)"),
    ("test", "Run tests", "tests/test_api.py::test_refund FAILED"),
    ("test", "Run tests", "E       KeyError: 'currency'"),
    ("test", "Run tests", "E       KeyError: 'currency'"),
    ("test", "Run tests", "FAILED tests/test_api.py::test_refund - KeyError: 'currency'"),
    ("test", "Run tests", "==== 1 failed, 40 passed in 3.21s ===="),
    ("test", "Run tests", "##[error]Process completed with exit code 1."),
    ("test", "Upload coverage", "Error: no coverage file found"),
    ("test", "Post Run actions/checkout@v4", "Cleaning up orphan processes"),
)

JUNIT = """<?xml version="1.0"?>
<testsuites><testsuite name="pytest" tests="3" failures="1">
  <testcase classname="tests.test_api" name="test_refund">
    <failure message="KeyError: 'currency'" type="KeyError">def test_refund(): ...</failure>
  </testcase>
  <testcase classname="tests.test_api" name="test_ok"/>
  <testcase classname="tests.test_net" name="test_fetch">
    <flakyFailure message="ConnectionResetError: connection reset by peer" type="ConnectionResetError"/>
  </testcase>
</testsuite></testsuites>
"""


def write(tmp_path):
    (tmp_path / "run.log").write_text(LOG, encoding="utf-8")
    (tmp_path / "junit.xml").write_text(JUNIT, encoding="utf-8")
    return tmp_path


def brief(source, goal="CI is red on main", **config):
    b = Briefing(CiAdapter(config), goal, trace=None, jev=FakeJev())
    b.extract(source)
    return b


def by_template(b):
    return {f.meta["template"]: f for f in b.facts}


def test_contract(tmp_path):
    check_adapter(CiAdapter(), write(tmp_path), goal="CI failed on main")


def test_classify():
    assert classify("E       KeyError: 'currency'") == "error"
    assert classify("found 0 errors in 212 packages") is None
    assert classify("npm WARN deprecated foo") == "warning"
    assert classify("##[warning]Node 16 is deprecated") == "warning"
    assert classify("Downloading packages") is None


def test_every_reason_code(tmp_path):
    b = brief(write(tmp_path))
    by = by_template(b)
    assert by["npm WARN deprecated <email>: This module is not supported"].reason == "ci.below_severity"
    assert by["==== <n> failed, <n> passed in <n> ===="].reason == "ci.summary_line"
    assert by["Process completed with exit code <n>."].reason == "ci.summary_line"
    assert by["src/api.py:<n>: error: unused import (continue-on-error step)"].reason == "ci.passed_step"
    assert by["Error: no coverage file found"].reason == "ci.after_failure"
    assert by["ConnectionResetError: connection reset by peer"].reason == "ci.passed_on_rerun"
    assert by["KeyError: 'currency'"].kept and by["KeyError: 'currency'"].reason == "ci.test_failure"
    first = by["tests/test_api.py::test_refund FAILED"]
    assert first.kept and first.reason == "ci.first_error" and first.attrs["where"] == "in the failing step"
    assert by["E KeyError: 'currency'"].reason == "ci.failed_step"
    assert b.source["failing_steps"] == {"test": "Run tests"}

    b = brief(write(tmp_path), min_severity="warning")
    assert by_template(b)["npm WARN deprecated <email>: This module is not supported"].reason == "ci.passed_step"


def test_attrs_and_flaky(tmp_path):
    (tmp_path / "net.log").write_text(gh_log(
        ("e2e", "Run", "Error: connect ETIMEDOUT 140.82.112.3:443"),
        ("e2e", "Run", "##[error]Process completed with exit code 1.")), encoding="utf-8")
    b = brief(tmp_path / "net.log")
    f = by_template(b)["Error: connect ETIMEDOUT <ip>"]
    assert f.kept and f.attrs == {"job": "e2e", "step": "Run", "severity": "error", "frequency": "once",
                                  "where": "in the failing step", "looks_flaky": "yes"}
    assert "flaky" in b.pack.build("g", b.kept, b.state())


def test_log_archive_zip(tmp_path):
    z = tmp_path / "logs.zip"
    with zipfile.ZipFile(z, "w") as w:
        w.writestr("0_build.txt", "whole job log: error everywhere\n")
        w.writestr("build/1_Set up job.txt", T.format(0) + " Runner ready\n")
        w.writestr("build/2_Compile.txt", T.format(1) + " main.c:9: error: 'x' undeclared\n"
                   + T.format(2) + " ##[error]Process completed with exit code 2.\n")
    b = brief(z)
    kept = [f for f in b.facts if f.kept]
    assert [f.meta["template"] for f in kept] == ["main.c:<n>: error: 'x' undeclared"]
    assert kept[0].attrs["step"] == "Compile" and not any("whole job" in f.label for f in b.facts)


def test_raw_arm_is_last_lines(tmp_path):
    a = CiAdapter()
    ex = a.extract(write(tmp_path))
    raw = a.raw(ex.facts)
    assert len(raw) == 12 and raw[-1].label == "Post Run actions/checkout@v4: Cleaning up orphan processes"


def test_real_log_noise_is_not_an_error(tmp_path):
    (tmp_path / "job.log").write_text("\n".join(T.format(i) + " " + line for i, line in enumerate([
        "##[group]Run pytest -v",
        "Traceback (most recent call last):",
        "    if error and self._is_read_error(error):",
        "error = SSLError('EOF')",
        "E       pexpect.exceptions.TIMEOUT: Timeout exceeded.",
        "E       buffer (last 100 chars): 'error'",
        "=================================== FAILURES ===================================",
        "##[end-action id=x]",
        "##[error]Process completed with exit code 1.",
        "Post job cleanup.",
        "Error: cache save failed",
    ])) + "\n", encoding="utf-8")
    b = brief(tmp_path / "job.log")
    kept = [f for f in b.facts if f.kept]
    assert [f.meta["template"] for f in kept] == ["E pexpect.exceptions.TIMEOUT: Timeout exceeded."]
    assert kept[0].attrs["step"] == "Run pytest -v" and kept[0].attrs["looks_flaky"] == "yes"
    assert {f.meta["template"]: f.reason for f in b.facts}["Error: cache save failed"] == "ci.after_failure"


def test_min_severity_as_an_extract_option(tmp_path):
    b = Briefing(CiAdapter(), "CI is red on main", trace=None, jev=FakeJev())
    b.extract(write(tmp_path), min_severity="warning")
    assert by_template(b)["npm WARN deprecated <email>: This module is not supported"].reason == "ci.passed_step"
