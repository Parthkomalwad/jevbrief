"""Choose which MCP tool an agent should call next.

Run:  python examples/mcp_tool.py "Why did the last CI run on main fail? Show me the failing job's output"
Uses the real tool lists in bench/mcp/tools (GitHub, git, fetch, time: 105 tools).
Your own servers: save each server's tools/list result as JSON in a folder, and pass --tools <folder>.
Needs TYPESAFE_API_KEY in the environment or in a .env file.
"""

import argparse

from jevbrief import Briefing
from jevbrief.adapters.mcp import McpAdapter
from jevbrief.cli import load_env


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("goal", nargs="*", default=["Why did the last CI run on main fail? Show me the failing job's output"])
    p.add_argument("--tools", default="bench/mcp/tools")
    p.add_argument("--read-only", action="store_true", help="never pick a tool that changes data")
    args = p.parse_args()
    load_env()

    brief = Briefing(McpAdapter({"read_only": args.read_only}), " ".join(args.goal), trace="traces/mcp.jsonl")
    brief.extract(args.tools)
    print(f"{brief.source['tools']} tools from {brief.source['servers']} servers -> {len(brief.kept)} sent to Jev")
    decision = brief.decide()
    if decision.fact:
        f = decision.fact
        print(f"call: {f.meta['server']}.{f.label}  (confidence {decision.confidence:.2f})")
        print(f"  {f.attrs}")
    else:
        top = next((f for f in brief.kept if f.id == decision.choice), None)
        pick = f"{top.meta['server']}.{top.label}" if top else decision.choice
        print(f"no tool called: {decision.outcome}, Jev's pick was {pick} at {decision.confidence or 0:.2f}")
    print("see it: jevbrief view traces/mcp.jsonl")


if __name__ == "__main__":
    main()
