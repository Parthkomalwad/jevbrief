"""Choose which tool an agent should call next, from your own functions plus real MCP tools.

Run:  python examples/tool_router.py "Why did the last CI run on main fail? Show me the failing job's output"
      python examples/tool_router.py "refund order 812, the customer was charged twice"
Uses the real MCP tool lists in bench/mcp/tools (GitHub, git, fetch, time: 105 tools) plus two custom functions.
Needs TYPESAFE_API_KEY in the environment or in a .env file (select_tools alone needs no key).
"""

import argparse
import json
from pathlib import Path

from jevbrief import pick_tool, select_tools
from jevbrief.cli import load_env


def refund_order(order_id: str, amount: float = 0.0):
    """Refund part or all of a customer's order."""


def lookup_customer(email: str):
    """Find a customer by their email address."""


lookup_customer.read_only = True


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("goal", nargs="*", default=["Why did the last CI run on main fail? Show me the failing job's output"])
    p.add_argument("--tools", default="bench/mcp/tools", help="a folder of MCP tools/list JSON files")
    p.add_argument("--read-only", action="store_true", help="never pick a tool that changes data")
    args = p.parse_args()
    load_env()
    goal = " ".join(args.goal)

    mcp = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(Path(args.tools).glob("*.json"))]
    tools = [refund_order, lookup_customer, *mcp]          # any mix: functions, MCP, LangChain, CrewAI, dicts

    top = select_tools(tools, goal, top_k=5, read_only=args.read_only)   # local, free
    print("top 5:", ", ".join(getattr(t, "__name__", None) or t["name"] for t in top))

    pick = pick_tool(tools, goal, read_only=args.read_only, trace="traces/tools.jsonl")
    if pick.tool:
        name = getattr(pick.tool, "__name__", None) or pick.tool["name"]
        print(f"call: {name}  (confidence {pick.confidence:.2f})")
    else:
        print(f"no tool called ({pick.decision.outcome}); fall back to the top {len(pick.tools)} tools")
    print("see it: jevbrief view traces/tools.jsonl")


if __name__ == "__main__":
    main()
