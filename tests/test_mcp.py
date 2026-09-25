import json

from jevbrief import Briefing
from jevbrief.adapters.mcp import McpAdapter, bm25, short, tool_lists, words
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
    b = Briefing(McpAdapter(config), goal, trace=None, jev=FakeJev())
    b.extract(data)
    return b


def reasons(b):
    return {f.label: f.reason for f in b.facts}


def test_contract(tmp_path):
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(SERVERS), encoding="utf-8")
    check_adapter(McpAdapter(), path, goal="open a bug report about the login page")


def test_input_shapes():
    one = {"tools": SERVERS["servers"]["time"]["tools"]}
    assert [s for s, _ in tool_lists(one)] == ["tools"]
    assert [s for s, _ in tool_lists({"jsonrpc": "2.0", "id": 1, "result": one})] == ["tools"]
    assert {s for s, _ in tool_lists(SERVERS)} == {"github", "filesystem", "time"}
    assert {s for s, _ in tool_lists(SERVERS["servers"])} == {"github", "filesystem", "time"}
    assert len(tool_lists([{"name": "a"}, {"name": "b", "server": "x"}])) == 2


def test_words_split_names():
    assert words("listPullRequests") == ["list", "pull", "request"]
    assert words("get_current_time") == ["current", "time"]  # "get" is a tool stopword
    assert words("repositories") == ["repository"]


def test_bm25_prefers_rare_matching_words():
    docs = [["create", "issue"], ["list", "issue"], ["read", "file"]]
    s = bm25(docs, ["create", "issue"])
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
    assert r["read_file"] == "mcp.not_relevant"

    r = reasons(brief("show the open pull requests", top_k=5))
    assert r["list_pull_requests"] == "goal_match"
    assert r["create_issue"] == "mcp.not_relevant"  # no shared word: dropped even inside top_k

    r = reasons(brief("read the config file", read_only=True))
    assert r["write_file"] == "mcp.writes" and r["delete_repository"] == "mcp.writes" and r["read_file"] == "goal_match"

    r = reasons(brief("read the config file", deny=["filesystem.*"]))
    assert r["read_file"] == "mcp.denied" and r["write_file"] == "mcp.denied"
    r = reasons(brief("read the config file", allow=["read_file"]))
    assert r["read_file"] == "goal_match" and r["write_file"] == "mcp.denied"

    r = reasons(brief("repository owner"))  # matches only parameter descriptions, not the label
    assert r["list_pull_requests"] == "mcp.relevant"


def test_question_and_raw():
    b = brief("open a new issue")
    q = b.pack.build(b.goal, b.kept, b.state())["next_tool"]
    assert "github.create_issue: Create a new issue in a GitHub repository." in q["criteria"].values()
    raw = McpAdapter().raw(b.facts)
    assert len(raw) == 6 and raw[0].attrs["params"] == "owner, repo, title"
