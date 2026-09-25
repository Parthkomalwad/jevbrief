import json
from types import SimpleNamespace

import pytest

import jevbrief
from jevbrief import Briefing
from jevbrief.adapters.tools import ToolsAdapter, bm25, pick_tool, select_tools, short, spec, tool_specs, words
from jevbrief.testing import FakeJev, check_adapter


def tool(name, description, required=(), read_only=None, destructive=None, **props):
    ann = {k: v for k, v in (("readOnlyHint", read_only), ("destructiveHint", destructive)) if v is not None}
    t = {"name": name, "description": description,
         "inputSchema": {"type": "object", "properties": {p: {"type": "string", "description": d} for p, d in props.items()},
                         "required": list(required)}}
    return {**t, "annotations": ann} if ann else t


SERVERS = {"servers": {
    "github": {"tools": [
        tool("create_issue", "Create a new issue in a GitHub repository.", ["owner", "repo", "title"], read_only=False,
             owner="Repository owner", repo="Repository name", title="Issue title"),
        tool("list_pull_requests", "List pull requests in a GitHub repository.", ["owner", "repo"], read_only=True,
             owner="Repository owner", repo="Repository name"),
        tool("delete_repository", "Delete a repository. This cannot be undone.", ["repo"], destructive=True,
             repo="Repository name"),
    ]},
    "filesystem": {"tools": [
        tool("read_file", "Read the complete contents of a file from the file system.", ["path"], read_only=True, path="File path"),
        tool("write_file", "Create a new file or overwrite an existing file with new content.", ["path", "content"],
             read_only=False, path="File path", content="Text"),
    ]},
    "time": {"tools": [tool("get_current_time", "Get the current time in a specific timezone.", ["timezone"], timezone="IANA name")]},
}}


def brief(goal, data=SERVERS, **config):
    b = Briefing(ToolsAdapter(config), goal, trace=None, jev=FakeJev())
    b.extract(data)
    return b


def reasons(b):
    return {f.label: f.reason for f in b.facts}


# --- The adapter ---

def test_contract(tmp_path):
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(SERVERS), encoding="utf-8")
    check_adapter(ToolsAdapter(), path, goal="open a bug report about the login page")


def test_folder_of_dumps(tmp_path):
    for name, v in SERVERS["servers"].items():
        (tmp_path / f"{name}.json").write_text(json.dumps({"server": name, **v}), encoding="utf-8")
    assert ToolsAdapter().extract(tmp_path).source["servers"] == 3


def test_mcp_container_shapes():
    one = {"tools": SERVERS["servers"]["time"]["tools"]}
    assert [s["server"] for s, _ in tool_specs(one)] == [None]
    assert len(tool_specs({"jsonrpc": "2.0", "id": 1, "result": one})) == 1
    assert {s["server"] for s, _ in tool_specs(SERVERS)} == {"github", "filesystem", "time"}
    assert {s["server"] for s, _ in tool_specs(SERVERS["servers"])} == {"github", "filesystem", "time"}


def test_words_split_names():
    assert words("listPullRequests") == ["list", "pull", "request"]
    assert words("get_current_time") == ["current", "time"]  # "get" is a tool stopword
    assert words("repositories") == ["repository"]
    assert words("summarize this page https://example.com/a?b=1") == ["summarize", "page", "url"]
    assert words("review my PR") == ["review", "pull", "request"]


def test_bm25_prefers_rare_matching_words():
    s = bm25([["create", "issue"], ["list", "issue"], ["read", "file"]], ["create", "issue"])
    assert s[0] > s[1] > s[2] == 0


def test_attrs_are_words():
    by = {f.label: f for f in brief("open a new issue for the crash").facts}
    assert by["create_issue"].attrs == {"server": "github", "description": "Create a new issue in a GitHub repository.",
                                        "needs": "owner, repo, title", "effect": "changes data"}
    assert by["read_file"].attrs["effect"] == "read-only"
    assert by["delete_repository"].attrs["effect"] == "destructive"
    assert "effect" not in by["get_current_time"].attrs
    assert short("One. " + "x" * 300) == ("One. " + "x" * 300)[:160].rsplit(" ", 1)[0] + "..."


def test_every_reason_code():
    b = brief("what time is it in Tokyo", top_k=1)
    r = reasons(b)
    assert r["get_current_time"] == "goal_match" and b.facts[-1].meta["rank"] == 1
    assert r["read_file"] == "tools.not_relevant"

    r = reasons(brief("show the open pull requests", top_k=5))
    assert r["list_pull_requests"] == "goal_match"
    assert r["create_issue"] == "tools.not_relevant"  # no shared word: dropped even inside top_k

    r = reasons(brief("read the config file", read_only=True))
    assert r["write_file"] == "tools.writes" and r["delete_repository"] == "tools.writes" and r["read_file"] == "goal_match"

    r = reasons(brief("read the config file", deny=["filesystem.*"]))
    assert r["read_file"] == "tools.denied" and r["write_file"] == "tools.denied"
    r = reasons(brief("read the config file", allow=["read_file"]))
    assert r["read_file"] == "goal_match" and r["write_file"] == "tools.denied"

    r = reasons(brief("repository owner"))  # matches only parameter descriptions, not the label
    assert r["list_pull_requests"] == "tools.relevant"


def test_same_name_on_two_servers_is_kept():
    data = {"github": {"tools": [tool("search_code", "Search code in GitHub repositories.")]},
            "gitlab": {"tools": [tool("search_code", "Search code in GitLab projects.")]}}
    assert sorted(f.meta["server"] for f in brief("search the code for parse_invoice", data).kept) == ["github", "gitlab"]


def test_question_and_raw():
    b = brief("open a new issue")
    q = b.pack.build(b.goal, b.kept, b.state())["next_tool"]
    assert "github.create_issue: Create a new issue in a GitHub repository." in q["criteria"].values()
    raw = ToolsAdapter().raw(b.facts)
    assert len(raw) == 6 and raw[0].attrs["params"] == "owner, repo, title"
    assert len(b.pack.build(b.goal, raw, {})["next_tool"]["criteria"]) == 7  # the raw arm builds the same question


# --- Any tool object ---

def refund_order(order_id: str, amount: float = 0.0, *, reason: str = ""):
    """Refund part or all of a customer's order.

    Longer notes that are not sent.
    """


def lookup_customer(email: str):
    """Find a customer by their email address."""


lookup_customer.read_only = True


class PydanticLike:  # stands in for a Pydantic model class, as LangChain and CrewAI use for args_schema
    @staticmethod
    def model_json_schema():
        return {"type": "object", "properties": {"city": {"type": "string", "description": "City name"}},
                "required": ["city"]}


def test_spec_reads_every_shape():
    f = spec(refund_order)
    assert f["name"] == "refund_order" and f["description"].startswith("Refund part or all")
    assert f["schema"]["required"] == ["order_id"] and set(f["schema"]["properties"]) == {"order_id", "amount", "reason"}
    assert spec(lookup_customer)["annotations"] == {"readOnlyHint": True}

    openai = {"type": "function", "function": {"name": "get_weather", "description": "Weather for a city.",
                                               "parameters": {"properties": {"city": {}}, "required": ["city"]}}}
    anthropic = {"name": "get_weather", "description": "Weather for a city.",
                 "input_schema": {"properties": {"city": {}}, "required": ["city"]}}
    langchain = SimpleNamespace(name="get_weather", description="Weather for a city.", args_schema=PydanticLike,
                                metadata={"server": "weather"})
    crewai = SimpleNamespace(name="get_weather", description="Weather for a city.", args_schema=PydanticLike)
    mcp_sdk = SimpleNamespace(name="get_weather", description="Weather for a city.", title=None,
                              inputSchema={"properties": {"city": {}}, "required": ["city"]},
                              annotations=SimpleNamespace(readOnlyHint=True))
    for obj in (openai, anthropic, langchain, crewai, mcp_sdk):
        s = spec(obj)
        assert (s["name"], s["description"], s["schema"]["required"]) == ("get_weather", "Weather for a city.", ["city"])
    assert spec(langchain)["server"] == "weather"
    assert spec(mcp_sdk)["annotations"] == {"readOnlyHint": True}
    assert spec({"no": "name"}) is None and spec(42) is None


def test_mixed_list_and_select_tools():
    weather = SimpleNamespace(name="get_weather", description="Current weather for a city.", args_schema=PydanticLike)
    mixed = [refund_order, lookup_customer, weather, *SERVERS["servers"]["github"]["tools"]]
    got = select_tools(mixed, "refund order 812 for the customer", top_k=3)
    assert got[0] is refund_order  # your own objects come back, most relevant first
    assert select_tools(mixed, "what's the weather in Paris?", top_k=2)[0] is weather
    assert select_tools(mixed, "find the customer with this email", read_only=True)[0] is lookup_customer
    assert refund_order not in select_tools(mixed, "refund the order", deny=["refund_order"])


def test_pick_tool_returns_your_object(tmp_path):
    mixed = [refund_order, lookup_customer]
    pick = pick_tool(mixed, "refund order 812", jev=FakeJev(), trace=str(tmp_path / "t.jsonl"))
    assert pick.tool is refund_order and pick.tools[0] is refund_order and pick.confidence == 0.9
    assert (tmp_path / "t.jsonl").exists()
    assert jevbrief.select_tools is select_tools and jevbrief.pick_tool is pick_tool  # the lazy top-level exports


def test_real_langchain_tools():
    lc = pytest.importorskip("langchain_core.tools")

    @lc.tool
    def search_orders(customer_email: str, status: str = "open") -> str:
        """Search a customer's orders by status."""
        return ""

    s = spec(search_orders)
    assert s["name"] == "search_orders" and s["description"].startswith("Search a customer's orders")
    assert s["schema"]["required"] == ["customer_email"]
    assert select_tools([search_orders, refund_order], "find the orders for this customer")[0] is search_orders


def test_real_mcp_sdk_tools():
    types = pytest.importorskip("mcp.types")
    t = types.Tool(name="get_weather", description="Weather for a city.",
                   inputSchema={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
                   annotations=types.ToolAnnotations(readOnlyHint=True))
    assert spec(t)["annotations"] == {"readOnlyHint": True} and spec(t)["schema"]["required"] == ["city"]
    assert select_tools([t, refund_order], "weather in Paris")[0] is t
