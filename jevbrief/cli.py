"""The `jevbrief` command line tool."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

from . import __version__


def load_env(path: str | Path = ".env") -> None:
    """Load KEY=VALUE lines from a .env file. Existing environment variables win."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


def to_url(target: str) -> str:
    p = Path(target)
    return p.resolve().as_uri() if p.exists() else target


async def open_page(url: str):
    """Start Chromium and open `url`. Returns (playwright, browser, page)."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch()
    page = await browser.new_page(viewport={"width": 1280, "height": 800})
    await page.goto(to_url(url), wait_until="load")
    return pw, browser, page


async def brief_page(url: str, goal: str, **kw):
    from .brief import Brief

    pw, browser, page = await open_page(url)
    try:
        brief = Brief(goal, **kw)
        await brief.from_page(page)
        return brief
    finally:
        await browser.close()
        await pw.stop()


def print_facts(brief) -> None:
    kept = sorted(brief.kept, key=lambda f: -f.score)
    dropped = [f for f in brief.facts if not f.kept]
    print(f"{len(brief.facts)} elements found, {len(kept)} kept, {len(dropped)} dropped, "
          f"~{brief.used_tokens} of {brief.budget_tokens} tokens\n")
    print("KEPT")
    for f in kept:
        print(f"  {f.id}  {f.score:.2f}  {f.kind:<7} {f.label!r:<45} {f.reason}")
    print("\nDROPPED")
    for reason, n in Counter(f.reason for f in dropped).most_common():
        print(f"  {reason} ({n})")
        for f in (f for f in dropped if f.reason == reason):
            print(f"    {f.id}  {f.kind:<7} {f.label!r}")


def cmd_inspect(a) -> int:
    brief = asyncio.run(brief_page(a.url, a.goal, budget_tokens=a.budget, trace=None, jev=_NoJev()))
    print_facts(brief)
    return 0


def cmd_ask(a) -> int:
    if not os.environ.get("TYPESAFE_API_KEY"):
        print("TYPESAFE_API_KEY is not set. Add it to your environment or a .env file.", file=sys.stderr)
        return 2
    brief = asyncio.run(brief_page(a.url, a.goal, budget_tokens=a.budget, trace=a.trace,
                                   min_confidence=a.min_confidence, trace_level=a.trace_level,
                                   screenshot=not a.no_screenshot))
    d = brief.next_click()
    conf = f"{d.confidence:.2f}" if d.confidence is not None else "-"
    label = d.fact.label if d.fact else "(no action)"
    print(f"outcome: {d.outcome}\nchoice: {d.choice} {label!r}\nconfidence: {conf}")
    if d.outcome == "error":
        print(f"error: {d.record.jev.get('error') if d.record else 'unknown'}", file=sys.stderr)
    if brief.trace_path and brief.trace_level != "off":
        print(f"trace: {brief.trace_path}")
        if a.view:
            from .viewer import open_viewer

            print(f"viewer: {open_viewer(brief.trace_path)}")
        else:
            print(f"see it: jevbrief view {brief.trace_path}")
    return 1 if d.outcome == "error" else 0


def cmd_view(a) -> int:
    from .viewer import open_viewer

    trace = a.trace or latest_trace()
    if not trace:
        print("No trace found in traces/. Run `jevbrief ask <url> --goal \"...\"` first.", file=sys.stderr)
        return 2
    print(f"trace: {trace}")
    path = open_viewer(trace, open_browser=not a.no_open)
    print(f"viewer: {path}")
    return 0


def cmd_bench(a) -> int:
    from .bench import run

    if not os.environ.get("TYPESAFE_API_KEY"):
        print("TYPESAFE_API_KEY is not set. Add it to your environment or a .env file.", file=sys.stderr)
        return 2
    print(run(a.tasks, repeats=a.repeats, out_dir=a.out))
    return 0


def latest_trace(folder: str = "traces") -> str | None:
    files = sorted(Path(folder).rglob("*.jsonl"), key=lambda p: p.stat().st_mtime) if Path(folder).is_dir() else []
    return str(files[-1]) if files else None


class _NoJev:
    """Placeholder so `inspect` never creates an API client."""
    model = "none"


def main(argv: list[str] | None = None) -> int:
    load_env()
    p = argparse.ArgumentParser(prog="jevbrief", description="Clean, traceable state briefings for TypeSafe's Jev model.")
    p.add_argument("--version", action="version", version=f"jevbrief {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def page_args(sp):
        sp.add_argument("url", help="Page URL or path to a local HTML file")
        sp.add_argument("--goal", required=True, help='What the agent is trying to do, e.g. "add to cart"')
        sp.add_argument("--budget", type=int, default=2000, help="Token budget for the state (default 2000)")

    sp = sub.add_parser("inspect", help="Show kept and dropped elements. No Jev call, no API key needed.")
    page_args(sp)
    sp.set_defaults(fn=cmd_inspect)

    sp = sub.add_parser("ask", help="Ask Jev which element to click next and write a trace.")
    page_args(sp)
    sp.add_argument("--trace", default="traces/trace.jsonl", help="Trace file (default traces/trace.jsonl)")
    sp.add_argument("--trace-level", default="summary", choices=["off", "summary", "full"])
    sp.add_argument("--min-confidence", type=float, default=0.5, help="Below this, take no action (default 0.5)")
    sp.add_argument("--view", action="store_true", help="Open the trace viewer when done")
    sp.add_argument("--no-screenshot", action="store_true", help="Do not store a page screenshot in the trace")
    sp.set_defaults(fn=cmd_ask)

    sp = sub.add_parser("view", help="Open a trace file in the HTML viewer (default: the newest in traces/).")
    sp.add_argument("trace", nargs="?", help="Path to a .jsonl trace file (default: newest file in traces/)")
    sp.add_argument("--no-open", action="store_true", help="Write the HTML file but do not open a browser")
    sp.set_defaults(fn=cmd_view)

    sp = sub.add_parser("bench", help="Run the benchmark: raw page state against jevbrief state.")
    sp.add_argument("tasks", nargs="?", default="bench/tasks.json", help="Tasks file (default bench/tasks.json)")
    sp.add_argument("--repeats", type=int, default=3, help="Runs per task and arm (default 3)")
    sp.add_argument("--out", default="traces/bench", help="Folder for benchmark traces")
    sp.set_defaults(fn=cmd_bench)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
