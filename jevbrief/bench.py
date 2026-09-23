"""Benchmark: raw page state against jevbrief state, same Jev, same question."""

from __future__ import annotations

import asyncio
import copy
import json
import statistics
from pathlib import Path

from . import budget
from .brief import Brief
from .dom import extract
from .jev import Jev

ARMS = ("raw", "jevbrief")


def _raw_brief(goal: str, facts, url: str, trace_path: str, jev: Jev) -> Brief:
    """Every extracted interactive element, no salience, document order, capped at the option limit."""
    b = Brief(goal, trace=trace_path, jev=jev, max_options=budget.MAX_OPTIONS, budget_tokens=budget.MAX_TOKENS)
    b.url = url
    b.facts = [f for f in facts if f.kind != "text"][: budget.MAX_OPTIONS]
    for f in b.facts:
        f.kept, f.reason, f.score = True, "raw", 0.0
    b.used_tokens = budget.estimate_tokens(b.state())
    return b


async def _extract_all(tasks: list[dict], base: Path):
    from playwright.async_api import async_playwright

    out = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        for t in tasks:
            await page.goto((base / t["fixture"]).resolve().as_uri(), wait_until="load")
            out.append((await extract(page), page.url))
        await browser.close()
    return out


def run(tasks_path: str, repeats: int = 3, out_dir: str = "traces/bench") -> str:
    tasks_file = Path(tasks_path)
    tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
    pages = asyncio.run(_extract_all(tasks, tasks_file.parent))
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    jev = Jev()
    rows = {arm: [] for arm in ARMS}
    per_task = []

    for t, (facts, url) in zip(tasks, pages):
        name = Path(t["fixture"]).stem
        line = {"task": name}
        for arm in ARMS:
            trace_path = str(Path(out_dir) / f"{arm}.jsonl")
            hits = 0
            for _ in range(repeats):
                fs = copy.deepcopy(facts)
                if arm == "raw":
                    b = _raw_brief(t["goal"], fs, url, trace_path, jev)
                else:
                    b = Brief(t["goal"], trace=trace_path, jev=jev)
                    b.load(fs, url)
                d = b.next_click()
                j = d.record.jev
                chosen = next((f for f in b.facts if f.id == d.choice), None)
                ok = bool(chosen and chosen.label.lower() == t["expected_label"].lower())
                hits += ok
                rows[arm].append({
                    "ok": ok, "tokens": j.get("input_tokens") or b.used_tokens,
                    "latency": j.get("latency_ms"), "confidence": j.get("confidence"),
                    "options": len(b.kept), "error": d.outcome == "error",
                })
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
        acc = sum(x["ok"] for x in r) / len(r) if r else 0
        errs = sum(x["error"] for x in r)
        conf = _med([x["confidence"] for x in r])
        out.append(f"| {arm} | {acc:.0%} ({sum(x['ok'] for x in r)}/{len(r)})"
                   f"{f', {errs} errors' if errs else ''} | {_med([x['tokens'] for x in r]):.0f} | "
                   f"{_med([x['latency'] for x in r]) or 0:.0f} | {conf if conf is None else f'{conf:.2f}'} | "
                   f"{_med([x['options'] for x in r]):.0f} |")
    out += ["", "| Task | raw | jevbrief |", "|---|---|---|"]
    out += [f"| {t['task']} | {t['raw']} | {t['jevbrief']} |" for t in per_task]
    return "\n".join(out)
