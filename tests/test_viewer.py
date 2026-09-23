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
