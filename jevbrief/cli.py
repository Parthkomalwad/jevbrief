"""The `jevbrief` command line tool."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from pathlib import Path

from . import __version__, adapters

NO_KEY = "TYPESAFE_API_KEY is not set. Add it to your environment or a .env file."


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


def make_briefing(a, **kw):
    from .briefing import Briefing

    adapter = adapters.get(a.adapter)
    if a.config:
        adapter.configure(a.config)
    b = Briefing(adapter, a.goal, budget_tokens=a.budget, pack=a.pack, **kw)
    b.extract(a.source)
    return b


def print_facts(b) -> None:
    kept = sorted(b.kept, key=lambda f: -f.score)
    dropped = [f for f in b.facts if not f.kept]
    print(f"{len(b.facts)} facts found, {len(kept)} kept, {len(dropped)} dropped, "
          f"~{b.used_tokens} of {b.budget_tokens} tokens\n")
    print("KEPT")
    for f in kept:
        print(f"  {f.id}  {f.score:.2f}  {f.kind:<7} {f.label!r:<45} {f.reason}")
    print("\nDROPPED")
    for reason, n in Counter(f.reason for f in dropped).most_common():
        print(f"  {reason} ({n})")
        for f in (f for f in dropped if f.reason == reason):
            print(f"    {f.id}  {f.kind:<7} {f.label!r}")


def cmd_inspect(a) -> int:
    print_facts(make_briefing(a, trace=None, trace_level="off"))
    return 0


def cmd_ask(a) -> int:
    if not os.environ.get("TYPESAFE_API_KEY"):
        print(NO_KEY, file=sys.stderr)
        return 2
    b = make_briefing(a, trace=a.trace, trace_level=a.trace_level, min_confidence=a.min_confidence,
                      images=not a.no_screenshot)
    d = b.decide()
    conf = f"{d.confidence:.2f}" if d.confidence is not None else "-"
    label = d.fact.label if d.fact else ""
    print(f"outcome: {d.outcome}\nchoice: {d.choice} {label!r}\nconfidence: {conf}")
    if d.outcome == "error":
        print(f"error: {d.record.jev.get('error') if d.record else 'unknown'}", file=sys.stderr)
    if b.trace_path and b.trace_level != "off":
        print(f"trace: {b.trace_path}")
        if a.view:
            from .viewer import open_viewer

            print(f"viewer: {open_viewer(b.trace_path)}")
        else:
            print(f"see it: jevbrief view {b.trace_path}")
    return 1 if d.outcome == "error" else 0


def cmd_view(a) -> int:
    from .viewer import open_viewer, serve_live

    trace = a.trace or latest_trace() or ("traces/trace.jsonl" if a.live else None)
    if a.live:
        server = serve_live(trace, port=a.port, open_browser=not a.no_open)
        print(f"trace: {trace}")
        print(f"live viewer: http://127.0.0.1:{server.server_port}/  (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.shutdown()
        return 0
    if not trace:
        print('No trace found in traces/. Run `jevbrief ask <source> --goal "..."` first.', file=sys.stderr)
        return 2
    print(f"trace: {trace}")
    print(f"viewer: {open_viewer(trace, open_browser=not a.no_open)}")
    return 0


def cmd_bench(a) -> int:
    from .bench import run

    if not os.environ.get("TYPESAFE_API_KEY"):
        print(NO_KEY, file=sys.stderr)
        return 2
    print(run(a.tasks, repeats=a.repeats, out_dir=a.out))
    return 0


def cmd_adapters(a) -> int:
    for name, target in sorted(adapters.available().items()):
        print(f"{name:<8} {target}")
    return 0


def latest_trace(folder: str = "traces") -> str | None:
    files = sorted(Path(folder).rglob("*.jsonl"), key=lambda p: p.stat().st_mtime) if Path(folder).is_dir() else []
    return str(files[-1]) if files else None


def main(argv: list[str] | None = None) -> int:
    load_env()
    p = argparse.ArgumentParser(prog="jevbrief", description="Clean, traceable state briefings for TypeSafe's Jev model.")
    p.add_argument("--version", action="version", version=f"jevbrief {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def source_args(sp):
        sp.add_argument("source", help="What to brief: a URL or HTML file (web), a JSON file (json), an OTLP JSON log export (otel), CI logs or JUnit XML (ci), tool lists or MCP tools/list JSON (tools), agent steps or a trace (steps), a PR diff or /pulls/{n}/files JSON (pr), ...")
        sp.add_argument("--goal", required=True, help='What the agent is trying to do, e.g. "add to cart"')
        sp.add_argument("--adapter", default="web", help="Source type (default: web). See `jevbrief adapters`")
        sp.add_argument("--config", help="Adapter config file (required by the json adapter)")
        sp.add_argument("--pack", help="Question pack to use (default: the adapter's first pack)")
        sp.add_argument("--budget", type=int, default=2000, help="Token budget for the state (default 2000)")

    sp = sub.add_parser("inspect", help="Show kept and dropped facts. No Jev call, no API key needed.")
    source_args(sp)
    sp.set_defaults(fn=cmd_inspect)

    sp = sub.add_parser("ask", help="Ask Jev the adapter's question and write a trace.")
    source_args(sp)
    sp.add_argument("--trace", default="traces/trace.jsonl", help="Trace file (default traces/trace.jsonl)")
    sp.add_argument("--trace-level", default="summary", choices=["off", "summary", "full"])
    sp.add_argument("--min-confidence", type=float, default=0.5, help="Below this, take no action (default 0.5)")
    sp.add_argument("--view", action="store_true", help="Open the trace viewer when done")
    sp.add_argument("--no-screenshot", action="store_true", help="Do not store an image in the trace")
    sp.set_defaults(fn=cmd_ask)

    sp = sub.add_parser("view", help="Open a trace file in the HTML viewer (default: the newest in traces/).")
    sp.add_argument("trace", nargs="?", help="Path to a .jsonl trace file (default: newest file in traces/)")
    sp.add_argument("--no-open", action="store_true", help="Write the HTML file but do not open a browser")
    sp.add_argument("--live", action="store_true", help="Serve the viewer on 127.0.0.1 and show new decisions as they are written")
    sp.add_argument("--port", type=int, default=8765, help="Port for --live (default 8765)")
    sp.set_defaults(fn=cmd_view)

    sp = sub.add_parser("bench", help="Run a benchmark: raw state against jevbrief state.")
    sp.add_argument("tasks", nargs="?", default="bench/tasks.json", help="Tasks file (default bench/tasks.json)")
    sp.add_argument("--repeats", type=int, default=3, help="Runs per task and arm (default 3)")
    sp.add_argument("--out", default="traces/bench", help="Folder for benchmark traces")
    sp.set_defaults(fn=cmd_bench)

    sp = sub.add_parser("adapters", help="List installed adapters.")
    sp.set_defaults(fn=cmd_adapters)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (ImportError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
