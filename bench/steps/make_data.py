"""Generate labeled agent histories for the steps adapter benchmark.

Each history is 10 to 30 tool calls from a coding agent working on GitHub, using real tool names from GitHub's
MCP server. It starts with ordinary exploration, then ends in one of four ways, which is the label:
stuck repeating, stuck failing, progressing, or done. Several endings look like loops but are progress
(paging, polling a job, a retry that works), and several look busy but are stuck (new search terms that
keep finding nothing).

The histories are synthetic, written while building the adapter. Treat the results as an illustration.
Run: python bench/steps/make_data.py
"""

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = {"owner": "acme", "repo": "shop"}


def call(tool, result=None, error=None, **args):
    return {"tool": tool, "args": {**REPO, **args}, "result": result, "error": error}


def exploration(rng, n):
    """Ordinary, varied steps: each brings something new."""
    files = ["src/invoice.py", "src/cart.py", "src/api/orders.py", "tests/test_invoice.py", "README.md",
             "src/payments/stripe.py", "src/models.py", "docs/setup.md"]
    out = []
    for i in range(n):
        kind = rng.choice(["file", "search", "issue", "commits"])
        if kind == "file":
            f = rng.choice(files)
            out.append(call("get_file_contents", f"{f}: {rng.randint(40, 400)} lines. def load_{i}(...): ...", path=f))
        elif kind == "search":
            q = rng.choice(["currency", "invoice total", "refund", "tax rate", "rounding"])
            out.append(call("search_code", f"{rng.randint(1, 9)} results for '{q}' in src/", query=f"{q} repo:acme/shop"))
        elif kind == "issue":
            n_ = rng.randint(100, 999)
            out.append(call("issue_read", f"Issue #{n_}: invoices show the wrong total for EUR orders (opened by a customer)", issue_number=n_))
        else:
            out.append(call("list_commits", f"{rng.randint(5, 30)} commits; latest: 'fix tax rounding' by dev{i}", sha="main"))
    return out


def endings(rng):
    """(label, goal, steps) for every ending. Labels list every verdict that is right."""
    E = []
    for k in (4, 6, 8):
        E.append((["stuck_repeating"], "Find where invoice totals are rounded",
                  [call("search_code", "0 results", query="round_total repo:acme/shop")] * k))
    for k in (3, 4):
        E.append((["stuck_repeating"], "Check that the working tree is clean before committing",
                  [call("git_status", "Changes not staged: src/invoice.py"), call("git_diff", "src/invoice.py: +2 -1")] * k))
    for terms in (["round_total", "roundTotal", "round total", "rounding total", "total_round"],
                  ["EUR bug", "euro total", "currency total bug", "wrong total EUR", "invoice EUR"]):
        E.append((["stuck_repeating"], "Find the code that computes the invoice total",
                  [call("search_code", "0 results", query=f"{t} repo:acme/shop") for t in terms]))
    E.append((["stuck_repeating"], "Read the payments module",
              [call("get_file_contents", "Not Found", path="src/payment/stripe.py")] * 5))

    for k in (3, 5, 6):
        E.append((["stuck_failing"], "Open a pull request with the invoice fix",
                  [call("create_pull_request", error="422 Validation Failed: No commits between main and fix-invoice",
                        head="fix-invoice", base="main", title="Fix invoice total")] * k))
    E.append((["stuck_failing"], "Re-run the failed CI workflow",
              [call("actions_run_trigger", error="403 Resource not accessible by integration", workflow_id="ci.yml")] * 4))
    E.append((["stuck_failing"], "Push the fix to the fix-invoice branch",
              [call("push_files", error="409 Conflict: branch fix-invoice is behind main", branch="fix-invoice",
                    message=f"fix invoice total (attempt {i})") for i in range(1, 5)]))
    E.append((["stuck_failing", "stuck_repeating"], "Merge pull request 91",
              [call("merge_pull_request", error="405 Pull Request is not mergeable: required checks have not passed",
                    pullNumber=91)] * 3 + [call("pull_request_read", "PR #91: checks failing (2 of 5)", pullNumber=91)]
              + [call("merge_pull_request", error="405 Pull Request is not mergeable: required checks have not passed",
                      pullNumber=91)] * 2))
    E.append((["stuck_failing"], "Read the invoice module from the release branch",
              [call("get_file_contents", error="404 Not Found: ref release-2.0", path="src/invoice.py", ref=r)
               for r in ("release-2.0", "release-2.0", "release-2.0", "release-2.0")]))

    E.append((["progressing"], "List every open bug in acme/shop",
              [call("list_issues", f"issues {p * 30 + 1}-{p * 30 + 30} of 214", state="OPEN", labels=["bug"], page=p)
               for p in range(1, 7)]))
    E.append((["progressing"], "Wait for the deploy workflow to finish",
              [call("actions_get", s, run_id=5521) for s in
               ("queued", "in_progress: build", "in_progress: test (2/5)", "in_progress: test (4/5)", "in_progress: deploy")]))
    E.append((["progressing"], "Get the tests passing on the fix-invoice branch",
              [call("actions_get", s, run_id=r) for r, s in
               ((601, "failure: 7 tests failed"), (602, "failure: 4 tests failed"), (603, "failure: 2 tests failed"),
                (604, "failure: 1 test failed: test_eur_rounding"))]))
    E.append((["progressing"], "Find the code that computes the invoice total",
              [call("search_code", "0 results", query="invoiceTotal repo:acme/shop"),
               call("search_code", "3 results: src/invoice.py:88, src/cart.py:40, tests/test_invoice.py:12",
                    query="total repo:acme/shop path:src"),
               call("get_file_contents", "src/invoice.py: def compute_total(items, currency): ... round(total, 2)",
                    path="src/invoice.py")]))
    E.append((["progressing"], "Open a pull request with the invoice fix",
              [call("create_pull_request", error="502 Bad Gateway", head="fix-invoice", base="main"),
               call("create_pull_request", "Created pull request #92: Fix invoice total", head="fix-invoice", base="main")]
              + [call("request_copilot_review", "Review requested", pullNumber=92)]))
    E.append((["progressing"], "Understand how refunds are computed",
              [call("get_file_contents", f"{f}: {n} lines", path=f) for f, n in
               (("src/refunds.py", 210), ("src/payments/stripe.py", 340), ("src/models.py", 512), ("tests/test_refunds.py", 180))]))
    E.append((["progressing"], "Review the changes in pull request 88",
              [call("pull_request_read", r, pullNumber=88, method=m) for m, r in
               (("get", "PR #88: Fix EUR rounding, 3 files changed"), ("get_files", "src/invoice.py, src/cart.py, tests/test_invoice.py"),
                ("get_diff", "src/invoice.py: -round(total) +round(total, 2)"), ("get_comments", "2 comments: 'LGTM', 'add a test for JPY'"))]))
    E.append((["progressing"], "Summarize every issue that mentions refunds",
              [call("issue_read", f"Issue #{n}: {t}", issue_number=n) for n, t in
               ((311, "refund shows twice"), (318, "refund for EUR is off by a cent"), (402, "partial refunds fail"),
                (455, "refund email not sent"))]))

    E.append((["done"], "Open a pull request with the invoice fix",
              [call("push_files", "Pushed 2 files to fix-invoice", branch="fix-invoice", message="Fix invoice total"),
               call("create_pull_request", "Created pull request #93: Fix invoice total https://github.com/acme/shop/pull/93",
                    head="fix-invoice", base="main", title="Fix invoice total")]))
    E.append((["done"], "Get the tests passing on the fix-invoice branch",
              [call("actions_get", "failure: 1 test failed", run_id=611), call("push_files", "Pushed 1 file", branch="fix-invoice"),
               call("actions_get", "success: all 214 tests passed", run_id=612)]))
    E.append((["done"], "Find which file defines compute_total",
              [call("search_code", "1 result: src/invoice.py:88 def compute_total(items, currency):",
                    query="def compute_total repo:acme/shop")]))
    E.append((["done", "stuck_repeating"], "Find which file defines compute_total",
              [call("search_code", "1 result: src/invoice.py:88 def compute_total(items, currency):",
                    query="def compute_total repo:acme/shop")] * 4))
    E.append((["done"], "Label issue 1203 as a bug",
              [call("issue_read", "Issue #1203: checkout button does nothing on Safari", issue_number=1203),
               call("issue_write", "Updated issue #1203: labels = bug", issue_number=1203, labels=["bug"], method="update")]))
    return E


def main():
    rng = random.Random(7)
    out = HERE / "histories"
    out.mkdir(exist_ok=True)
    tasks = []
    for i, (labels, goal, ending) in enumerate(endings(rng)):
        history = exploration(rng, rng.randint(6, 22)) + ending
        name = f"h{i:02d}_{labels[0]}.json"
        (out / name).write_text(json.dumps(history, indent=1) + "\n", encoding="utf-8")
        tasks.append({"adapter": "steps", "source": f"histories/{name}", "goal": goal,
                      "expected_choice": labels if len(labels) > 1 else labels[0]})
    (HERE / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    counts = {}
    for t in tasks:
        k = t["expected_choice"] if isinstance(t["expected_choice"], str) else t["expected_choice"][0]
        counts[k] = counts.get(k, 0) + 1
    print(f"{len(tasks)} histories: {counts}")


if __name__ == "__main__":
    main()
