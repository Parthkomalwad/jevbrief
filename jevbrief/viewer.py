"""Render a JSONL trace into the single-file HTML viewer. Images are embedded, so it works offline.

`serve_live()` serves the same viewer from 127.0.0.1 and streams new decisions as they are written
(Server-Sent Events), plus the latest game frame from `<trace>.live.png` when a game writes one.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PLACEHOLDER = "/*__TRACES__*/[]"
POLL_S = 0.25


def _embed(record: dict, base: Path) -> dict:
    img = record.get("image")
    if img and img.get("path"):
        f = base / img["path"]
        if f.is_file():
            data = f.read_bytes()
            mime = "image/png" if data[:4] == b"\x89PNG" else mimetypes.guess_type(f.name)[0] or "image/jpeg"
            img["src"] = f"data:{mime};base64," + base64.b64encode(data).decode()
    return record


def _lines(trace_path: Path) -> list[str]:
    """Complete lines only: a line still being written has no newline yet."""
    try:
        text = trace_path.read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return []
    return [line for line in text.split("\n")[:-1] if line.strip()]


def render(trace_path: str | Path, live: bool = False) -> str:
    trace_path = Path(trace_path)
    lines = _lines(trace_path) if live else trace_path.read_text(encoding="utf-8").splitlines()
    records = [_embed(json.loads(line), trace_path.parent) for line in lines if line.strip()]
    data = json.dumps(records, ensure_ascii=False).replace("</", "<\\/")
    html = files("jevbrief").joinpath("viewer.html").read_text(encoding="utf-8").replace(PLACEHOLDER, data)
    if live:
        html = html.replace("</body>", LIVE_JS.replace("__FROM__", str(len(lines))) + "</body>")
    return html


def open_viewer(trace_path: str | Path, open_browser: bool = True) -> Path:
    out = Path(tempfile.gettempdir()) / f"jevbrief-{Path(trace_path).stem}.html"
    out.write_text(render(trace_path), encoding="utf-8")
    if open_browser:
        webbrowser.open(out.as_uri())
    return out


# Added to the page only by the live server. Follows the newest decision unless you pick an older one.
LIVE_JS = """<script>
(() => {
  const card = document.createElement("div");
  card.className = "card";
  card.style.cssText = "position:fixed;right:16px;bottom:16px;width:min(42vw,392px);z-index:10;margin:0";
  card.innerHTML = '<div class="bar">Live &#9642; <span id="live-status">waiting for decisions</span></div>'
    + '<img id="live-frame" alt="Latest game frame" style="display:none;width:100%;image-rendering:pixelated">';
  document.body.append(card);
  const img = card.querySelector("img");
  const next = () => setTimeout(() => { img.src = "/frame.png?t=" + Date.now(); }, 150);
  img.onload = () => { img.style.display = ""; next(); };
  img.onerror = () => setTimeout(next, 1000);
  next();
  let follow = true;
  $("list").addEventListener("click", () => { follow = selected === records.length - 1; });
  const es = new EventSource("/events?from=__FROM__");
  es.onmessage = (e) => {
    records.push(JSON.parse(e.data));
    if (!$("q").value) visible = records.map((_, i) => i);
    if (follow) { select(records.length - 1); play(true); } else renderList();
    $("live-status").textContent = records.length + " decisions, live";
    $("meta").textContent = `${records.length} decisions · live`;
  };
  es.onerror = () => { $("live-status").textContent = "reconnecting"; };
  if (records.length) { select(records.length - 1); play(true); }
})();
</script>
"""


def _handler(trace_path: Path):
    frame = trace_path.with_suffix(".live.png")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, body: bytes, ctype: str, code: int = 200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/":
                return self._send(render(trace_path, live=True).encode(), "text/html; charset=utf-8")
            if url.path == "/frame.png":
                try:
                    return self._send(frame.read_bytes(), "image/png")
                except OSError:
                    return self._send(b"no frame yet", "text/plain", 404)
            if url.path == "/events":
                return self._events(int(parse_qs(url.query).get("from", ["0"])[0]))
            self._send(b"not found", "text/plain", 404)

        def _events(self, sent: int):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    lines = _lines(trace_path)
                    for line in lines[sent:]:
                        rec = _embed(json.loads(line), trace_path.parent)
                        self.wfile.write(b"data: " + json.dumps(rec, ensure_ascii=False).encode() + b"\n\n")
                    if len(lines) > sent:
                        sent = len(lines)
                    else:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    time.sleep(POLL_S)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    return Handler


def serve_live(trace_path: str | Path, port: int = 8765, open_browser: bool = True) -> ThreadingHTTPServer:
    """Start the live viewer on 127.0.0.1 in a background thread. Returns the server; call `.shutdown()` to stop.

    Event streams run in daemon threads and end when the browser disconnects or the process exits."""
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(Path(trace_path)))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{server.server_port}/")
    return server
