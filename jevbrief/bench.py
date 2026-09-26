"""Benchmark: raw state against jevbrief state, same Jev, same question, any adapter.

A tasks file is a JSON list. Paths are relative to the tasks file:
    {"source": "fixtures/cart.html", "goal": "...", "expected_label": "Proceed to checkout"}
    {"adapter": "json", "source": "q.json", "config": "q.toml", "goal": "...", "expected_choice": "t-102"}
`adapter` defaults to "web". The old key "fixture" is accepted for "source".
"""

from __future__ import annotations

import copy
import statistics
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import adapters, budget, trace
from .briefing import Briefing
from .jev import Jev, JevClient
from .rules import RuleSet

ARMS = ("raw", "jevbrief")


def _raw(adapter, goal, ex, trace_path, jev) -> Briefing:
    """Every fact a naive integration would send: no rules, capped at the option limit."""
    b = Briefing(adapter, goal, rules=RuleSet([], threshold=0), trace=trace_path, jev=jev,
                 max_options=budget.MAX_OPTIONS, budget_tokens=budget.MAX_TOKENS)
    ex = copy.deepcopy(ex)
    ex.facts = (ex.raw if ex.raw is not None else adapter.raw(ex.facts))[: budget.MAX_OPTIONS]
    b.load_extracted(ex)
    for f in b.facts:
        f.reason = "raw"
    return b


LABELS = ("expected_choice", "expected_contains", "expected_label", "flaky")


def _correct(task, d, b) -> bool:
    if "flaky" in task and not any(k in task for k in LABELS[:3]):  # scored on the pack's `flaky` Noul
        p = (d.answers.get("flaky") or {}).get("noul")
        return p is not None and (p > 0.5) == task["flaky"]
    if "expected_choice" in task:  # an option, or a list of options any of which is right
        want = task["expected_choice"]
        return d.choice in ([want] if isinstance(want, str) else want)
    chosen = next((f for f in b.facts if f.id == d.choice), None)
    if "expected_contains" in task:  # a string, or a list of strings any of which is right
        text = f"{chosen.label} {chosen.meta.get('template', '')}".lower() if chosen else ""
        want = task["expected_contains"]
        return any(w.lower() in text for w in ([want] if isinstance(want, str) else want))
    want = task["expected_label"]  # a label, or a list of labels any of which is right
    return bool(chosen and chosen.label.lower() in [w.lower() for w in ([want] if isinstance(want, str) else want)])


def run(tasks_path: str, repeats: int = 3, out_dir: str = "traces/bench", jev: JevClient | None = None,
        workers: int = 4) -> str:
    """Run every labeled task `repeats` times per arm and return the results as Markdown tables.

    Jev calls run on `workers` threads. Traces are written afterwards on this thread, in task order.
    """
    import json

    tasks_file = Path(tasks_path)
    tasks = [t for t in json.loads(tasks_file.read_text(encoding="utf-8"))
             if any(k in t for k in LABELS)]  # tasks without a label are collected but not labeled yet
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    jev = jev or Jev()

    prepared = []
    for t in tasks:
        adapter = adapters.get(t.get("adapter", "web"))
        src = tasks_file.parent / (t.get("source") or t["fixture"])
        if t.get("config"):
            adapter.configure(str(tasks_file.parent / t["config"]))
        name = src.stem if t.get("adapter", "web") == "web" else f"{src.stem}: {t['goal'][:40]}"
        prepared.append((t, adapter, adapter.extract(str(src)), name))

    def one(job):
        (t, adapter, ex, _), arm = prepared[job[0]], job[1]
        if arm == "raw":
            b = _raw(adapter, t["goal"], ex, None, jev)
        else:
            b = Briefing(adapter, t["goal"], trace=None, jev=jev)
            b.load_extracted(copy.deepcopy(ex))
        return b, b.decide()

    jobs = [(i, arm, k) for i in range(len(prepared)) for arm in ARMS for k in range(repeats)]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(one, jobs))

    rows: dict[str, list[dict]] = {arm: [] for arm in ARMS}
    hits: dict[tuple[int, str], int] = {}
    for (i, arm, _), (b, d) in zip(jobs, results, strict=True):
        t = prepared[i][0]
        if d.record:
            trace.write(Path(out_dir) / f"{arm}.jsonl", d.record, image=b.image)
        j = d.record.jev if d.record else {}
        ok = _correct(t, d, b)
        hits[(i, arm)] = hits.get((i, arm), 0) + ok
        p = (d.answers.get("flaky") or {}).get("noul")
        flaky_ok = None if "flaky" not in t or p is None else (p > 0.5) == t["flaky"]
        rows[arm].append({"ok": ok, "flaky_ok": flaky_ok, "tokens": j.get("input_tokens") or b.used_tokens,
                          "latency": j.get("latency_ms"), "confidence": j.get("confidence"),
                          "options": len(b.kept), "error": d.outcome == "error"})

    per_task = []
    for i, (_, _, _, name) in enumerate(prepared):
        line = {"task": name, **{arm: f"{hits[(i, arm)]}/{repeats}" for arm in ARMS}}
        per_task.append(line)
        print(f"  {line['task']:<16} raw {line['raw']}  jevbrief {line['jevbrief']}", flush=True)
    return _table(rows, per_task)


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _table(rows: dict, per_task: list[dict]) -> str:
    flaky = any(x.get("flaky_ok") is not None for r in rows.values() for x in r)
    out = ["| Arm | Accuracy |" + (" Flaky accuracy |" if flaky else "")
           + " Median input tokens | Median latency (ms) | Median confidence | Median options |",
           "|---|---|" + ("---|" if flaky else "") + "---|---|---|---|"]
    for arm in ARMS:
        r = rows[arm]
        hits = sum(x["ok"] for x in r)
        errs = sum(x["error"] for x in r)
        conf = _med([x["confidence"] for x in r])
        fl = [x["flaky_ok"] for x in r if x.get("flaky_ok") is not None]
        fcol = f" {sum(fl) / len(fl) if fl else 0:.0%} ({sum(fl)}/{len(fl)}) |" if flaky else ""
        out.append(f"| {arm} | {hits / len(r) if r else 0:.0%} ({hits}/{len(r)})"
                   f"{f', {errs} errors' if errs else ''} |{fcol} {_med([x['tokens'] for x in r]) or 0:.0f} | "
                   f"{_med([x['latency'] for x in r]) or 0:.0f} | {'-' if conf is None else f'{conf:.2f}'} | "
                   f"{_med([x['options'] for x in r]) or 0:.0f} |")
    out += ["", "| Task | raw | jevbrief |", "|---|---|---|"]
    out += [f"| {t['task']} | {t['raw']} | {t['jevbrief']} |" for t in per_task]
    return "\n".join(out)
