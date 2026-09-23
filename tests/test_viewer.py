import json

from jevbrief.viewer import PLACEHOLDER, render


def test_render_injects_records_and_escapes_script_tags(tmp_path):
    rec = {"tick": 1, "goal": "</script><b>x", "facts": [], "jev": {}, "outcome": "error"}
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    html = render(path)
    assert PLACEHOLDER not in html
    assert "</script><b>x" not in html
    assert "<\\/script><b>x" in html
    assert "http://" not in html and "https://" not in html  # no external resources


def test_view_without_path_uses_newest_trace(tmp_path, monkeypatch):
    import os
    import time

    from jevbrief.cli import latest_trace

    monkeypatch.chdir(tmp_path)
    assert latest_trace() is None
    (tmp_path / "traces" / "bench").mkdir(parents=True)
    old, new = tmp_path / "traces" / "old.jsonl", tmp_path / "traces" / "bench" / "new.jsonl"
    old.write_text("{}\n")
    new.write_text("{}\n")
    os.utime(old, (time.time() - 60, time.time() - 60))
    assert latest_trace() == str(new.relative_to(tmp_path))


def test_replay_button_restarts_the_animation(tmp_path):
    pytest = __import__("pytest")
    sync_api = pytest.importorskip("playwright.sync_api")
    from jevbrief import Briefing
    from jevbrief.adapters.json import JsonAdapter
    from jevbrief.testing import FakeJev
    from jevbrief.viewer import open_viewer

    config = {"items": "rows", "id": "{id}", "label": "{name}"}
    b = Briefing(JsonAdapter(config), "find alpha", trace=str(tmp_path / "t.jsonl"), jev=FakeJev())
    b.extract({"rows": [{"id": "a", "name": "Alpha"}, {"id": "b", "name": "Beta"}]})
    b.decide()
    html = open_viewer(tmp_path / "t.jsonl", open_browser=False)
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(html.as_uri())
        page.click("#skip")
        steps = "document.querySelectorAll('#story .steps li.on').length"
        assert page.evaluate(steps) == 4
        page.click("#replay")
        page.wait_for_timeout(300)
        assert page.evaluate(steps) == 1  # restarted, not skipped to the end
        browser.close()


def test_live_server_serves_page_and_streams_new_decisions(tmp_path):
    import urllib.request

    from jevbrief.viewer import serve_live

    trace = tmp_path / "t.jsonl"
    rec = {"tick": 1, "goal": "g", "facts": [], "jev": {}, "outcome": "applied"}
    trace.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    server = serve_live(trace, port=0, open_browser=False)
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "EventSource" in page and '"tick": 1' in page
        with urllib.request.urlopen(base + "/events?from=1", timeout=5) as stream:
            with trace.open("a", encoding="utf-8") as f:
                f.write(json.dumps({**rec, "tick": 2}) + "\n")
            line = b""
            while not line.startswith(b"data: "):
                line = stream.readline()
            assert json.loads(line[6:])["tick"] == 2
    finally:
        server.shutdown()


def test_static_view_has_no_live_code(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    assert "EventSource" not in render(path)
