"""Benchmark: raw state against jevbrief state, same Jev, same question, any adapter.

A tasks file is a JSON list. Paths are relative to the tasks file:
    {"source": "fixtures/cart.html", "goal": "...", "expected_label": "Proceed to checkout"}
    {"adapter": "json", "source": "q.json", "config": "q.toml", "goal": "...", "expected_choice": "t-102"}
`adapter` defaults to "web". The old key "fixture" is accepted for "source".
"""

from __future__ import annotations

import copy
import statistics
from pathlib import Path

from . import adapters, budget
from .briefing import Briefing
from .jev import Jev
from .rules import RuleSet

ARMS = ("raw", "jevbrief")


def _raw(adapter, goal, ex, trace_path, jev) -> Briefing:
    """Every fact a naive integration would send: no rules, capped at the option limit."""
    b = Briefing(adapter, goal, rules=RuleSet([], threshold=0), trace=trace_path, jev=jev,
                 max_options=budget.MAX_OPTIONS, budget_tokens=budget.MAX_TOKENS)
    ex = copy.deepcopy(ex)
    ex.facts = adapter.raw(ex.facts)[: budget.MAX_OPTIONS]
    b.load_extracted(ex)
    for f in b.facts:
        f.reason = "raw"
    return b


def _correct(task, d, b) -> bool:
    if "expected_choice" in task:
        return d.choice == task["expected_choice"]
    chosen = next((f for f in b.facts if f.id == d.choice), None)
    return bool(chosen and chosen.label.lower() == task["expected_label"].lower())


def run(tasks_path: str, repeats: int = 3, out_dir: str = "traces/bench") -> str:
    import json

    tasks_file = Path(tasks_path)
    tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    jev = Jev()
    rows = {arm: [] for arm in ARMS}
    per_task = []

    for t in tasks:
        adapter = adapters.get(t.get("adapter", "web"))
        src = tasks_file.parent / (t.get("source") or t["fixture"])
        if t.get("config"):
            adapter.configure(str(tasks_file.parent / t["config"]))
        ex = adapter.extract(str(src))
        name = src.stem if t.get("adapter", "web") == "web" else f"{src.stem}: {t['goal'][:40]}"
        line = {"task": name}
        for arm in ARMS:
            trace_path = str(Path(out_dir) / f"{arm}.jsonl")
            hits = 0
            for _ in range(repeats):
                if arm == "raw":
                    b = _raw(adapter, t["goal"], ex, trace_path, jev)
                else:
                    b = Briefing(adapter, t["goal"], trace=trace_path, jev=jev)
                    b.load_extracted(copy.deepcopy(ex))
                d = b.decide()
                j = d.record.jev
                ok = _correct(t, d, b)
                hits += ok
                rows[arm].append({"ok": ok, "tokens": j.get("input_tokens") or b.used_tokens,
                                  "latency": j.get("latency_ms"), "confidence": j.get("confidence"),
                                  "options": len(b.kept), "error": d.outcome == "error"})
            line[arm] = f"{hits}/{repeats}"
        per_task.append(line)
        print(f"  {line['task']:<16} raw {line['raw']}  jevbrief {line['jevbrief']}", flush=True)
    return _table(rows, per_task)


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _table(rows: dict, per_task: list[dict]) -> str:
    out = ["| Arm | Accuracy | Median input tokens | Median latency (ms) | Median confidence | Median options |",
           "|---|---|---|---|---|---|"]
    for arm in ARMS:
        r = rows[arm]
        hits = sum(x["ok"] for x in r)
        errs = sum(x["error"] for x in r)
        conf = _med([x["confidence"] for x in r])
        out.append(f"| {arm} | {hits / len(r) if r else 0:.0%} ({hits}/{len(r)})"
                   f"{f', {errs} errors' if errs else ''} | {_med([x['tokens'] for x in r]) or 0:.0f} | "
                   f"{_med([x['latency'] for x in r]) or 0:.0f} | {'-' if conf is None else f'{conf:.2f}'} | "
                   f"{_med([x['options'] for x in r]) or 0:.0f} |")
    out += ["", "| Task | raw | jevbrief |", "|---|---|---|"]
    out += [f"| {t['task']} | {t['raw']} | {t['jevbrief']} |" for t in per_task]
    return "\n".join(out)
