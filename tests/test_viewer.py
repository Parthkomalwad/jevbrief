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
