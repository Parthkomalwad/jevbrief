"""Record the real tool lists of MCP servers, for the mcp adapter benchmark.

Starts each server over stdio, sends `initialize` and `tools/list` (JSON-RPC, following pages), and
writes `bench/mcp/tools/<server>.json` as `{"server": ..., "version": ..., "tools": [...]}`.
Standard library only. Servers that need a token get a placeholder: listing tools does not call their API.

Run: python bench/mcp/fetch_tools.py                 # every server in SERVERS
     python bench/mcp/fetch_tools.py time git       # only these
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "tools"
PY = sys.executable

# name -> command. Python servers run from the current environment (pip install them first);
# the others need Docker (docker pull the image first).
SERVERS = {
    "time": [PY, "-m", "mcp_server_time"],
    "fetch": [PY, "-m", "mcp_server_fetch"],
    "git": [PY, "-m", "mcp_server_git"],
    # Set GITHUB_MCP_BIN to a github-mcp-server release binary to run it without Docker.
    "github": ([os.environ["GITHUB_MCP_BIN"], "stdio", "--toolsets", "all"] if os.environ.get("GITHUB_MCP_BIN") else
               ["docker", "run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "-e", "GITHUB_TOOLSETS=all",
                "ghcr.io/github/github-mcp-server"]),
    "filesystem": ["docker", "run", "-i", "--rm", "mcp/filesystem", "/tmp"],
    "memory": ["docker", "run", "-i", "--rm", "mcp/memory"],
    "sequentialthinking": ["docker", "run", "-i", "--rm", "mcp/sequentialthinking"],
    "puppeteer": ["docker", "run", "-i", "--rm", "mcp/puppeteer"],
    "slack": ["docker", "run", "-i", "--rm", "-e", "SLACK_BOT_TOKEN=placeholder", "-e", "SLACK_TEAM_ID=T0",
              "mcp/slack"],
    "postgres": ["docker", "run", "-i", "--rm", "mcp/postgres", "postgresql://localhost/placeholder"],
}


class Server:
    def __init__(self, cmd: list[str]):
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, encoding="utf-8", bufsize=1)
        self.n = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        result: dict = {}

        def read():
            for line in self.p.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a server printing a banner on stdout
                if msg.get("id") == self.n:
                    result.update(msg)
                    return

        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(timeout)
        if "error" in result:
            raise RuntimeError(result["error"])
        if "result" not in result:
            raise TimeoutError(f"no answer to {method} within {timeout:.0f}s")
        return result["result"]

    def notify(self, method: str) -> None:
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.p.stdin.flush()

    def close(self):
        self.p.kill()


def fetch(name: str, cmd: list[str]) -> dict:
    s = Server(cmd)
    try:
        info = s.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "jevbrief-bench", "version": "1"}})
        s.notify("notifications/initialized")
        tools, cursor = [], None
        while True:
            page = s.call("tools/list", {"cursor": cursor} if cursor else {})
            tools += page.get("tools", [])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        return {"server": name, "version": info.get("serverInfo", {}).get("version", ""), "tools": tools}
    finally:
        s.close()


def main():
    OUT.mkdir(exist_ok=True)
    names = sys.argv[1:] or list(SERVERS)
    for name in names:
        cmd = SERVERS[name]
        if cmd[0] == "docker" and not shutil.which("docker"):
            print(f"{name:20} skipped: docker not found")
            continue
        try:
            data = fetch(name, cmd)
        except Exception as e:
            print(f"{name:20} failed: {type(e).__name__}: {str(e)[:120]}")
            continue
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{name:20} {len(data['tools']):3} tools  {data['version']}")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"] = "placeholder"  # listing tools makes no API call
    main()
