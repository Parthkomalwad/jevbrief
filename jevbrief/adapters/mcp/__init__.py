"""The mcp adapter: MCP tool lists to tool facts, for choosing which tool an agent should call next.

Reads the result of MCP `tools/list` (`{"tools": [...]}`), a folder of them, several of them keyed by server
(`{"servers": {"github": {"tools": [...]}, ...}}` or `{"github": {"tools": [...]}}`), or a plain list of
tool dicts, from a file or from Python. Standard library only.

Choosing 30 relevant tools out of 300 is a relevance problem, which fixed rules cannot solve. A cheap
BM25 keyword ranking against the goal runs first, and only the top tools are sent to Jev; the rest are
dropped as `mcp.not_relevant`, with their rank in the trace.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from ...briefing import Extracted
from ...facts import Fact, clean_label, fact_id, register_reasons
from ...questions import FactChoice
from ...rules import CORE_RULES, Drop, GroupRule, Rule, RuleSet, STOPWORDS
from .. import Adapter

NOT_RELEVANT = "mcp.not_relevant"
DENIED = "mcp.denied"
WRITES = "mcp.writes"
REASONS = {
    NOT_RELEVANT: "Ranked below the top tools for this goal by keyword relevance (BM25)",
    DENIED: "Excluded by the allow or deny list",
    WRITES: "Changes or deletes data, and only read-only tools are allowed",
    "mcp.relevant": "Kept: among the top tools for this goal by keyword relevance",
}
TOP_K = 30
DESCRIPTION_MAX = 160
# Words that appear in most tool descriptions and say nothing about which tool fits.
TOOL_STOPWORDS = STOPWORDS | set("tool tools use used using can will get returns return given specified "
                                 "optional required value values data".split())


# Common abbreviations in goals, expanded to the words tool descriptions use. Deliberately short and generic.
ABBREVIATIONS = {"pr": "pull request", "prs": "pull request", "repo": "repository", "repos": "repository",
                 "dir": "directory", "config": "configuration", "msg": "message", "db": "database"}
URL = re.compile(r"\b(?:https?://|www\.)\S+", re.I)


def words(text: str) -> list[str]:
    """Lowercase word stems, with snake_case, camelCase, and kebab-case split: `listPullRequests` -> list pull request.
    Any URL becomes the word `url`."""
    text = URL.sub(" url ", str(text))
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    out = []
    for raw in re.findall(r"[a-z0-9]+", text.lower()):
        for w in ABBREVIATIONS.get(raw, raw).split():
            if w in TOOL_STOPWORDS:
                continue
            w = w[:-3] + "y" if w.endswith("ies") and len(w) > 4 else w.rstrip("s") if len(w) > 3 else w
            if w and w not in TOOL_STOPWORDS:
                out.append(w)
    return out


def bm25(docs: list[list[str]], query: list[str], k1: float = 1.2, b: float = 0.75) -> list[float]:
    """Okapi BM25 score of each document for the query."""
    n = len(docs)
    avg = sum(map(len, docs)) / n if n else 0
    df = Counter(w for d in docs for w in set(d))
    scores = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for q in set(query):
            if tf[q]:
                idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
                s += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * len(d) / (avg or 1)))
        scores.append(s)
    return scores


def tool_lists(data) -> list[tuple[str, dict]]:
    """(server, tool) pairs from any of the accepted shapes."""
    if isinstance(data, list):
        if all(isinstance(t, dict) and "name" in t for t in data):
            return [(t.get("server", "tools"), t) for t in data]
        return [p for d in data for p in tool_lists(d)]
    if not isinstance(data, dict):
        return []
    if "result" in data:  # a raw JSON-RPC response
        return tool_lists(data["result"])
    if "tools" in data:
        server = data.get("server") or data.get("serverInfo", {}).get("name") or "tools"
        return [(t.get("server", server), t) for t in data["tools"]]
    servers = data.get("servers", data)
    return [(name, t) for name, v in servers.items() if isinstance(v, dict)
            for _, t in tool_lists({**v, "server": name})]


def effect(tool: dict) -> str | None:
    """From MCP tool annotations: "read-only", "destructive", "changes data", or None when not declared."""
    a = tool.get("annotations") or {}
    if a.get("readOnlyHint") is True:
        return "read-only"
    if a.get("destructiveHint") is True:
        return "destructive"
    if a.get("readOnlyHint") is False or a.get("destructiveHint") is False:
        return "changes data"
    return None


def short(text: str, limit: int = DESCRIPTION_MAX) -> str:
    """The first sentence or paragraph of a description, cut at a word boundary."""
    text = " ".join(str(text or "").split("\n\n")[0].split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    text = first if len(first) >= 30 else text
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


class McpAdapter(Adapter):
    """Options (a dict: `McpAdapter({"top_k": 20, "read_only": True})`):

    top_k      how many tools the ranking keeps (default 30)
    allow      tool names or "server.*" patterns to consider; everything else is dropped
    deny       tool names or "server.*" patterns to drop
    read_only  True drops tools whose annotations say they change or delete data
    """

    name = "mcp"
    version = "1"
    renderer = "table"
    extra = "mcp"
    reasons = REASONS

    def __init__(self, config=None):
        register_reasons(REASONS)
        self.config: dict = dict(config or {})

    def configure(self, config) -> None:
        self.config = dict(config or {})

    def extract(self, source, **options) -> Extracted:
        data = source
        if isinstance(source, (str, Path)):
            path = Path(source)
            files = sorted(path.glob("*.json")) if path.is_dir() else [path]  # a folder of tools/list dumps
            data = [json.loads(f.read_text(encoding="utf-8")) for f in files]
        pairs = tool_lists(data)
        if not pairs:
            raise ValueError("no tools found. Expected an MCP tools/list result: {\"tools\": [...]}")
        facts = []
        for i, (server, t) in enumerate(pairs):
            schema = t.get("inputSchema") or {}
            props = schema.get("properties") or {}
            required = [p for p in schema.get("required", []) if p in props] or []
            attrs = {"server": server, "description": short(t.get("description") or t.get("title") or "")}
            if required:
                attrs["needs"] = ", ".join(required[:6])
            if effect(t):
                attrs["effect"] = effect(t)
            text = " ".join([t["name"], t.get("title") or "", t.get("description") or "",
                             " ".join(props), " ".join(str(p.get("description", "")) for p in props.values()
                                                       if isinstance(p, dict))])
            facts.append(Fact(id=fact_id("mcp", server, t["name"]), kind="tool", label=clean_label(t["name"]),
                              attrs=attrs, meta={"order": i, "server": server, "words": words(text),
                                                 "description": t.get("description") or "", "params": list(props),
                                                 "name_words": words(t["name"])}))
        return Extracted(facts, {"name": Path(source).name if isinstance(source, (str, Path)) else "tools",
                                 "tools": len(facts), "servers": len({s for s, _ in pairs})})

    def rules(self) -> RuleSet:
        c = self.config
        hidden, disabled, unlabeled, goal_match, _ = CORE_RULES
        top_k = int(c.get("top_k", TOP_K))

        def listed(f, patterns):
            return any(p == f.label or p == f"{f.meta['server']}.{f.label}" or
                       (p.endswith(".*") and p[:-2] == f.meta["server"]) for p in patterns)

        def rank(facts, ctx):
            """Score every remaining tool against the goal. Name matches count double."""
            live = [f for f in facts if f.kept]
            query = words(ctx.goal)
            scores = bm25([f.meta["words"] + f.meta["name_words"] for f in live], query)
            order = sorted(range(len(live)), key=lambda i: (-scores[i], live[i].meta["order"]))
            for r, i in enumerate(order):
                f = live[i]
                f.meta["rank"], f.meta["relevance"] = r + 1, round(scores[i], 3)
                if r >= top_k or scores[i] <= 0:
                    f.drop(NOT_RELEVANT)
                else:
                    f.score = round(f.score + 0.5 * (1 - r / top_k), 4)
                    f.reason = "mcp.relevant" if f.reason == "base" else f.reason

        return RuleSet([
            hidden, disabled, unlabeled,
            Rule(DENIED, lambda f, ctx: Drop(DENIED) if (c.get("allow") and not listed(f, c["allow"]))
                 or listed(f, c.get("deny", [])) else None),
            Rule(WRITES, lambda f, ctx: Drop(WRITES) if c.get("read_only")
                 and f.attrs.get("effect") in ("changes data", "destructive") else None),
            goal_match,
            GroupRule(NOT_RELEVANT, rank),
            # No core `duplicate` rule: the same tool name on two servers (github.search_code, gitlab.search_code)
            # is two different tools.
        ])

    def packs(self):
        pack = FactChoice(
            "next_tool",
            "Agent goal: {goal}\n"
            "Each item in `tools` is a tool the agent can call. Which one tool should the agent call next "
            "to make progress on this goal?",
            lambda f: f"{f.meta.get('server', f.attrs.get('server'))}.{f.label}: {short(f.attrs.get('description', ''))}",
            none_text="No tool fits; the agent should answer directly or ask the user",
        )
        return {pack.name: pack}

    def state(self, goal, kept, source):
        return {"goal": goal, "tools": [f.state() for f in kept]}

    def raw(self, facts):
        """What a naive integration sends: every tool with its full description and input schema names."""
        return [Fact(id=f.id, kind="tool", label=f.label,
                     attrs={"server": f.meta["server"], "description": f.meta["description"],
                            "params": ", ".join(f.meta["params"])},
                     meta={"order": f.meta["order"], "server": f.meta["server"]}) for f in facts]
