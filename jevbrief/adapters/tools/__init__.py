"""The tools adapter: any list of agent tools to tool facts, for choosing which tool to call next.

Takes tools in whatever shape the developer already has, and can mix them in one list:
- your own Python functions (name, docstring, and signature)
- MCP tools: `tools/list` results, a folder of them, servers keyed by name, or MCP SDK `Tool` objects
- LangChain and LangGraph tools, including those from `langchain-mcp-adapters`
- CrewAI tools, including those from `MCPServerAdapter`
- OpenAI and Anthropic tool dicts

No framework is imported: fields are read from the objects. Standard library only.

Choosing 20 relevant tools out of 300 is a relevance problem, which fixed rules cannot solve. A cheap
BM25 keyword ranking against the goal runs first, and only the top tools are sent to Jev; the rest are
dropped as `tools.not_relevant`, with their rank in the trace.

    from jevbrief import select_tools, pick_tool
    llm.bind_tools(select_tools(my_tools, goal))       # ranking only: local, free, returns your objects
    pick = pick_tool(my_tools, goal)                   # also asks Jev: pick.tool, pick.tools, pick.confidence
"""

from __future__ import annotations

import inspect
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ...briefing import Briefing, Decision, Extracted
from ...facts import Fact, clean_label, fact_id, register_reasons
from ...questions import FactChoice
from ...rules import CORE_RULES, STOPWORDS, Drop, GroupRule, Rule, RuleSet
from .. import Adapter, need

NOT_RELEVANT = "tools.not_relevant"
DENIED = "tools.denied"
WRITES = "tools.writes"
REASONS = {
    NOT_RELEVANT: "Ranked below the top tools for this goal (keyword or embedding relevance)",
    DENIED: "Excluded by the allow or deny list",
    WRITES: "Changes or deletes data, and only read-only tools are allowed",
    "tools.relevant": "Kept: among the top tools for this goal by keyword relevance",
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


# --- Embedding ranking (optional) --------------------------------------------------------------------

RANKS = ("bm25", "embedding", "hybrid")
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
RRF_K = 60  # reciprocal rank fusion constant: how much the top of each ranking dominates


class Embedder:
    """Turns texts into vectors, caching every tool text it has seen. Wraps either your own function
    (`embed(list_of_texts) -> list_of_vectors`, used for both tools and goals) or fastembed's local model."""

    def __init__(self, fn=None, model: str = DEFAULT_MODEL):
        self.fn, self.model, self._fast, self._cache = fn, model, None, {}

    def _fastembed(self):
        if self._fast is None:
            need("embed", "fastembed")
            from fastembed import TextEmbedding

            self._fast = TextEmbedding(self.model)
        return self._fast

    def documents(self, texts: list[str]) -> list[list[float]]:
        todo = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if todo:
            vecs = self.fn(todo) if self.fn else self._fastembed().passage_embed(todo)
            self._cache.update(zip(todo, (list(map(float, v)) for v in vecs)))
        return [self._cache[t] for t in texts]

    def query(self, text: str) -> list[float]:
        if self.fn:
            return list(map(float, self.fn([text])[0]))
        return list(map(float, next(iter(self._fastembed().query_embed([text])))))


_EMBEDDERS: dict = {}  # one per function or model, so the cache survives across calls


def embedder(embed=None) -> Embedder:
    """An Embedder for `embed`: None (fastembed's default model), a model name, a function, or an Embedder."""
    if isinstance(embed, Embedder):
        return embed
    key = embed if callable(embed) else (embed or DEFAULT_MODEL)
    if key not in _EMBEDDERS:
        _EMBEDDERS[key] = Embedder(embed) if callable(embed) else Embedder(model=key)
    return _EMBEDDERS[key]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# --- Reading any tool object -------------------------------------------------------------------------

def _dict(obj) -> dict:
    """A plain dict from a dict, a Pydantic model, or an object with attributes."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump(exclude_none=True)
    return {k: v for k, v in vars(obj).items() if not k.startswith("_")} if hasattr(obj, "__dict__") else {}


def _schema(s) -> dict:
    """A JSON schema from a dict, a Pydantic model class, or nothing."""
    if isinstance(s, dict):
        return s
    if hasattr(s, "model_json_schema"):
        try:
            return s.model_json_schema()
        except Exception:
            return {}
    return {}


def _function_schema(fn) -> dict:
    """A JSON schema from a Python function's signature: every parameter, required when it has no default."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return {}
    props, required = {}, []
    for name, p in sig.parameters.items():
        if name in ("self", "cls") or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        ann = p.annotation
        props[name] = {"type": getattr(ann, "__name__", str(ann))} if ann is not p.empty else {}
        if p.default is p.empty:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def spec(obj, server: str | None = None) -> dict | None:
    """Normalize one tool to {"name", "description", "schema", "annotations", "server"}, or None if it is not a tool.

    Reads, in order: OpenAI tool dicts, other dicts (MCP, Anthropic, custom), objects with `name` and
    `description` (MCP SDK, LangChain, CrewAI), and plain functions.
    """
    if isinstance(obj, dict):
        d = obj.get("function") if obj.get("type") == "function" and isinstance(obj.get("function"), dict) else obj
        if "name" not in d:
            return None
        schema = d.get("inputSchema") or d.get("input_schema") or d.get("parameters") or {}
        extra = obj
    elif hasattr(obj, "name") and (hasattr(obj, "description") or hasattr(obj, "inputSchema")):
        d = {"name": obj.name, "description": getattr(obj, "description", "") or "",
             "title": getattr(obj, "title", None)}
        schema = getattr(obj, "inputSchema", None) or getattr(obj, "args_schema", None) or \
            getattr(obj, "input_schema", None) or {}
        if not _schema(schema) and callable(getattr(obj, "func", None)):  # LangChain tools made from functions
            schema = _function_schema(obj.func)
        extra = {"annotations": getattr(obj, "annotations", None), "server": getattr(obj, "server", None),
                 "read_only": getattr(obj, "read_only", None), "destructive": getattr(obj, "destructive", None),
                 **(getattr(obj, "metadata", None) or {})}
    elif callable(obj) and hasattr(obj, "__name__"):
        doc = inspect.getdoc(obj) or ""
        d = {"name": obj.__name__, "description": doc}
        schema = _function_schema(obj)
        extra = {"server": getattr(obj, "server", None), "read_only": getattr(obj, "read_only", None),
                 "destructive": getattr(obj, "destructive", None)}
    else:
        return None
    ann = _dict(extra.get("annotations"))
    for key, hint in (("read_only", "readOnlyHint"), ("destructive", "destructiveHint")):
        if extra.get(key) is not None:  # a custom tool's own flag
            ann.setdefault(hint, bool(extra[key]))
    return {"name": str(d["name"]), "description": str(d.get("description") or d.get("title") or ""),
            "schema": _schema(schema), "annotations": ann,
            "server": extra.get("server") or extra.get("mcp_server") or server}


def tool_specs(data, server: str | None = None) -> list[tuple[dict, object]]:
    """(spec, original object) pairs from a tool, a list of tools, or an MCP container, in order."""
    if isinstance(data, (list, tuple)):
        return [p for item in data for p in tool_specs(item, server)]
    if isinstance(data, dict) and "name" not in data:
        if "result" in data:  # a raw JSON-RPC response
            return tool_specs(data["result"], server)
        if "tools" in data:  # a tools/list result
            name = data.get("server") or (data.get("serverInfo") or {}).get("name") or server
            return tool_specs(data["tools"], name)
        servers = data.get("servers", data)  # {"github": {"tools": [...]}, ...}
        return [p for name, v in servers.items() if isinstance(v, (dict, list)) for p in tool_specs(v, name)]
    s = spec(data, server)
    return [(s, data)] if s else []


def effect(annotations: dict) -> str | None:
    """From MCP-style annotations: "read-only", "destructive", "changes data", or None when not declared."""
    if annotations.get("readOnlyHint") is True:
        return "read-only"
    if annotations.get("destructiveHint") is True:
        return "destructive"
    if annotations.get("readOnlyHint") is False or annotations.get("destructiveHint") is False:
        return "changes data"
    return None


def short(text: str, limit: int = DESCRIPTION_MAX) -> str:
    """The first sentence or paragraph of a description, cut at a word boundary."""
    text = " ".join(str(text or "").split("\n\n")[0].split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    text = first if len(first) >= 30 else text
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def qualified(f: Fact) -> str:
    return f"{f.meta['server']}.{f.label}" if f.meta.get("server") else f.label


# --- The adapter -------------------------------------------------------------------------------------

class ToolsAdapter(Adapter):
    """Options (a dict: `ToolsAdapter({"top_k": 20, "read_only": True})`):

    top_k      how many tools the ranking keeps (default 30)
    allow      tool names, "server.tool", or "server.*" to consider; everything else is dropped
    deny       tool names, "server.tool", or "server.*" to drop
    read_only  True drops tools that declare they change or delete data
    rank       "bm25" (default, keywords), "embedding" (meaning), or "hybrid" (both, fused by rank)
    embed      for embedding and hybrid: your function `texts -> vectors`, or a fastembed model name.
               Default: fastembed's BAAI/bge-small-en-v1.5, a local model (`pip install "jevbrief[embed]"`)
    """

    name = "tools"
    version = "1"
    renderer = "table"
    extra = "tools"
    reasons = REASONS

    def __init__(self, config=None):
        register_reasons(REASONS)
        self.config: dict = dict(config or {})

    def configure(self, config) -> None:
        """A dict, or a path to a JSON file of options."""
        if isinstance(config, (str, Path)):
            config = json.loads(Path(config).read_text(encoding="utf-8"))
        self.config = dict(config or {})

    def extract(self, source, **options) -> Extracted:
        data = source
        if isinstance(source, (str, Path)):
            path = Path(source)
            files = sorted(path.glob("*.json")) if path.is_dir() else [path]  # a folder of tools/list dumps
            data = [json.loads(f.read_text(encoding="utf-8")) for f in files]
        pairs = tool_specs(data)
        if not pairs:
            raise ValueError("no tools found. Pass functions, tool objects, tool dicts, or an MCP tools/list result")
        facts = []
        for i, (s, obj) in enumerate(pairs):
            props = s["schema"].get("properties") or {}
            required = [p for p in s["schema"].get("required", []) if p in props]
            attrs = {"server": s["server"]} if s["server"] else {}
            attrs["description"] = short(s["description"])
            if required:
                attrs["needs"] = ", ".join(required[:6])
            if effect(s["annotations"]):
                attrs["effect"] = effect(s["annotations"])
            text = " ".join([s["name"], s["description"], " ".join(props),
                             " ".join(str(p.get("description", "")) for p in props.values() if isinstance(p, dict))])
            facts.append(Fact(id=fact_id("tools", s["server"] or "", s["name"]), kind="tool",
                              label=clean_label(s["name"]), attrs=attrs,
                              meta={"order": i, "server": s["server"], "words": words(text),
                                    "name_words": words(s["name"]), "description": s["description"],
                                    "embed_text": f"{' '.join(words(s['name']))}: {short(s['description'], 300)}",
                                    "params": list(props), "obj": obj}))
        return Extracted(facts, {"name": Path(source).name if isinstance(source, (str, Path)) else "tools",
                                 "tools": len(facts), "servers": len({s["server"] for s, _ in pairs if s["server"]})})

    def rules(self) -> RuleSet:
        c = self.config
        hidden, disabled, unlabeled, goal_match, _ = CORE_RULES
        top_k = int(c.get("top_k", TOP_K))
        mode = c.get("rank", "bm25")
        if mode not in RANKS:
            raise ValueError(f"rank must be one of {', '.join(RANKS)}")

        def listed(f, patterns):
            server = f.meta.get("server")
            return any(p == f.label or (server and (p == f"{server}.{f.label}" or p == f"{server}.*"))
                       for p in patterns)

        def rank(facts, ctx):
            """Order every remaining tool by relevance to the goal: keywords (BM25, words in the tool name count
            double), meaning (embedding cosine similarity), or both fused by reciprocal rank."""
            live = [f for f in facts if f.kept]
            if not live:
                return
            scores = bm25([f.meta["words"] + f.meta["name_words"] for f in live], words(ctx.goal))
            by_kw = sorted(range(len(live)), key=lambda i: (-scores[i], live[i].meta["order"]))
            sims = [0.0] * len(live)
            if mode != "bm25":
                e = embedder(c.get("embed"))
                q = e.query(ctx.goal)
                sims = [cosine(q, v) for v in e.documents([f.meta["embed_text"] for f in live])]
            by_sim = sorted(range(len(live)), key=lambda i: (-sims[i], live[i].meta["order"]))
            if mode == "bm25":
                order = by_kw
            elif mode == "embedding":
                order = by_sim
            else:
                fused = [0.0] * len(live)
                for ranking in (by_kw, by_sim):
                    for r, i in enumerate(ranking):
                        fused[i] += 1 / (RRF_K + r + 1)
                order = sorted(range(len(live)), key=lambda i: (-fused[i], live[i].meta["order"]))
            for r, i in enumerate(order):
                f = live[i]
                f.meta["rank"], f.meta["relevance"] = r + 1, round(scores[i], 3)
                if mode != "bm25":
                    f.meta["similarity"] = round(sims[i], 3)
                if r >= top_k or (mode == "bm25" and scores[i] <= 0):  # no shared word only matters for keywords
                    f.drop(NOT_RELEVANT)
                else:
                    f.score = round(f.score + 0.5 * (1 - r / top_k), 4)
                    f.reason = "tools.relevant" if f.reason == "base" else f.reason

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
            lambda f: f"{qualified(f)}: {short(f.attrs.get('description', ''))}",
            none_text="No tool fits; the agent should answer directly or ask the user",
        )
        return {pack.name: pack}

    def state(self, goal, kept, source):
        return {"goal": goal, "tools": [f.state() for f in kept]}

    def raw(self, facts):
        """What a naive integration sends: every tool with its full description and parameter names."""
        return [Fact(id=f.id, kind="tool", label=f.label,
                     attrs={**({"server": f.meta["server"]} if f.meta.get("server") else {}),
                            "description": f.meta["description"], "params": ", ".join(f.meta["params"])},
                     meta={"order": f.meta["order"], "server": f.meta.get("server")}) for f in facts]


# --- The one-call API --------------------------------------------------------------------------------

@dataclass
class Pick:
    """What `pick_tool` returns. `tool` is your own object, or None when Jev is unsure or no tool fits."""
    tool: object | None
    tools: list                    # the narrowed list, most relevant first: a fallback when `tool` is None
    confidence: float | None
    decision: Decision | None = field(default=None, repr=False)


def _brief(tools, goal, top_k, allow, deny, read_only, rank="bm25", embed=None, **briefing) -> Briefing:
    config = {"top_k": top_k, "allow": allow or [], "deny": deny or [], "read_only": read_only,
              "rank": rank, "embed": embed}
    b = Briefing(ToolsAdapter(config), goal, **briefing)
    b.extract(tools)
    return b


def _ranked(b: Briefing) -> list:
    return [f.meta["obj"] for f in sorted(b.kept, key=lambda f: f.meta["rank"])]


def select_tools(tools, goal: str, *, top_k: int = 20, allow=None, deny=None, read_only: bool = False,
                 rank: str = "bm25", embed=None) -> list:
    """The `top_k` tools most relevant to `goal`, most relevant first, as the same objects you passed in.

    No Jev call and no API key. Pass the result straight to your framework, for example
    `llm.bind_tools(select_tools(tools, goal))` or `Agent(tools=select_tools(tools, task))`.
    `rank="hybrid"` adds meaning to keywords, so "bug report" finds an issue tool; see `ToolsAdapter`.
    """
    return _ranked(_brief(tools, goal, top_k, allow, deny, read_only, rank, embed, trace=None, trace_level="off"))


def pick_tool(tools, goal: str, *, top_k: int = 20, allow=None, deny=None, read_only: bool = False,
              rank: str = "bm25", embed=None, trace: str | None = "traces/tools.jsonl",
              min_confidence: float = 0.5, **briefing) -> Pick:
    """Rank the tools, then ask Jev which one to call next. Returns a `Pick` with your own objects.

    `pick.tool` is None when Jev is below `min_confidence` or says no tool fits; use `pick.tools`, the
    narrowed list, as the fallback. Every call is written to `trace` for `jevbrief view`.
    """
    b = _brief(tools, goal, top_k, allow, deny, read_only, rank, embed, trace=trace, min_confidence=min_confidence,
               **briefing)
    d = b.decide()
    return Pick(d.fact.meta["obj"] if d.fact else None, _ranked(b), d.confidence, d)
