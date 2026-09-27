"""Collect real screens and taps from Google's AndroidControl dataset for the android adapter benchmark.

AndroidControl (Apache 2.0, https://github.com/google-research/google-research/tree/master/android_control)
records people doing tasks in 833 real apps: for each step, the screen's accessibility tree, a screenshot,
a step instruction ("Click on the search icon"), and the action taken. This collector streams one data file
over HTTPS and stops after `--episodes` episodes, so only a few hundred MB are downloaded, not the 2.5 GB file.
Standard library only: a streaming TFRecord reader and a small protobuf decoder for the fields used.

For every click or long press:
- the screen is saved as a UI element list (`screens/<episode>_<step>.json`, no screenshot)
- the goal is the step instruction
- the expected answer is the element that was tapped: the smallest interactive element containing the tap
  point, plus any interactive element that is nearly the same box (a wrapper around it). Where a drawer or
  dialog covers other elements this can pick one underneath, so labels are reviewed by hand

Labels are automatic ("review": "auto"). Review them before any run, and never change them after.

Run: python bench/android/fetch_androidcontrol.py --episodes 30
"""

from __future__ import annotations

import argparse
import gzip
import json
import struct
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from jevbrief.adapters.android import AndroidAdapter  # noqa: E402

URL = "https://storage.googleapis.com/gresearch/android_control/android_control-{:05d}-of-00020"


# Protobuf wire format: just enough to read tf.train.Example and android_env's accessibility forest.

def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def fields(buf: bytes) -> dict[int, list]:
    """Field number -> list of raw values (ints for varints, bytes for length-delimited)."""
    out: dict[int, list] = {}
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        num, wire = key >> 3, key & 7
        if wire == 0:
            v, i = _varint(buf, i)
        elif wire == 2:
            n, i = _varint(buf, i)
            v, i = buf[i:i + n], i + n
        elif wire == 5:
            v, i = buf[i:i + 4], i + 4
        elif wire == 1:
            v, i = buf[i:i + 8], i + 8
        else:
            raise ValueError(f"unsupported wire type {wire}")
        out.setdefault(num, []).append(v)
    return out


def _s(f: dict, n: int) -> str:
    return f[n][0].decode("utf-8", "replace") if n in f else ""


def _b(f: dict, n: int) -> bool:
    return bool(f[n][0]) if n in f else False


def example(buf: bytes) -> dict[str, list]:
    """A tf.train.Example as name -> list of values (bytes or ints)."""
    out = {}
    for entry in fields(fields(buf)[1][0]).get(1, []):
        e = fields(entry)
        name, feat = e[1][0].decode(), fields(e[2][0]) if 2 in e else {}
        if 1 in feat:      # bytes_list
            out[name] = fields(feat[1][0]).get(1, [])
        elif 3 in feat:    # int64_list, packed
            packed, vals, i = fields(feat[3][0]).get(1, [b""])[0], [], 0
            if isinstance(packed, int):
                vals = fields(feat[3][0])[1]
            else:
                while i < len(packed):
                    v, i = _varint(packed, i)
                    vals.append(v)
            out[name] = vals
        elif 2 in feat:    # float_list, packed
            packed = fields(feat[2][0]).get(1, [b""])[0]
            out[name] = list(struct.unpack(f"<{len(packed) // 4}f", packed))
    return out


def ui_elements(forest: bytes) -> list[dict]:
    """The accessibility forest as a flat UI element list, the format the android adapter reads."""
    out = []
    for window in fields(forest).get(1, []):
        w = fields(window)
        for tree in w.get(11, []):
            for node in fields(tree).get(1, []):
                n = fields(node)
                r = fields(n[2][0]) if 2 in n else {}
                box = {k: r.get(i, [0])[0] for i, k in ((1, "x_min"), (2, "y_min"), (3, "x_max"), (4, "y_max"))}
                out.append({"text": _s(n, 7), "content_description": _s(n, 4), "hint_text": _s(n, 5),
                            "class_name": _s(n, 3), "package_name": _s(n, 6), "resource_name": _s(n, 10),
                            "is_checkable": _b(n, 12), "is_checked": _b(n, 13), "is_clickable": _b(n, 14),
                            "is_editable": _b(n, 15), "is_enabled": _b(n, 16), "is_focusable": _b(n, 17),
                            "is_long_clickable": _b(n, 19), "is_scrollable": _b(n, 21), "is_selected": _b(n, 22),
                            "is_visible": _b(n, 23), "bbox_pixels": box})
    return out


def records(url: str):
    """Records of a GZIP TFRecord file, streamed: [length u64][crc u32][data][crc u32]."""
    with urllib.request.urlopen(url, timeout=120) as resp, gzip.GzipFile(fileobj=resp) as f:
        while True:
            head = f.read(12)
            if len(head) < 12:
                return
            (n,) = struct.unpack("<Q", head[:8])
            data = f.read(n)
            f.read(4)
            yield data


def label(screen_path: Path, x: float, y: float) -> tuple[list[str], str]:
    """Fact IDs of the tapped element: the smallest interactive element containing the point, plus any that is
    nearly the same box (a wrapper around it).

    Not the topmost element by drawing order: AndroidControl's drawing order only ranks siblings, so it cannot
    be compared across the screen. The smallest element is right except where a drawer or dialog covers
    other elements; those labels are fixed by hand review."""
    facts = AndroidAdapter().extract(str(screen_path)).facts
    hits = []
    for f in facts:
        b = f.meta.get("box")
        if f.kind != "text" and b and b[0] <= x <= b[0] + b[2] and b[1] <= y <= b[1] + b[3] and b[2] * b[3] > 0:
            hits.append((b[2] * b[3], f))
    if not hits:
        return [], ""
    smallest = min(a for a, _ in hits)
    chosen = sorted((f for a, f in hits if a <= smallest * 1.25), key=lambda f: f.meta["box"][2] * f.meta["box"][3])
    return [f.id for f in chosen], chosen[0].label


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--shard", type=int, default=0)
    p.add_argument("--episodes", type=int, default=30)
    p.add_argument("--max-steps", type=int, default=4, help="most tap steps kept per episode, for variety")
    p.add_argument("--tasks", default="tasks.json", help="tasks file to write, in this folder (default tasks.json)")
    args = p.parse_args()
    out = HERE / "screens"
    out.mkdir(exist_ok=True)
    tasks, skipped, episodes = [], {"no element at the tap": 0, "unlabeled target": 0}, 0
    for rec in records(URL.format(args.shard)):
        ex = example(rec)
        episodes += 1
        ep = ex["episode_id"][0]
        goal = ex["goal"][0].decode()
        actions = [json.loads(a) for a in ex["actions"]]
        steps = [s.decode() for s in ex.get("step_instructions", [])]
        kept = 0
        for i, act in enumerate(actions):
            if act.get("action_type") not in ("click", "long_press") or kept >= args.max_steps:
                continue
            w, h = ex["screenshot_widths"][i], ex["screenshot_heights"][i]
            path = out / f"{ep}_{i}.json"
            path.write_text(json.dumps({"screen": [w, h], "ui_elements": ui_elements(ex["accessibility_trees"][i])}),
                            encoding="utf-8")
            ids, target = label(path, act["x"], act["y"])
            if not ids or not target:
                skipped["no element at the tap" if not ids else "unlabeled target"] += 1
                path.unlink()
                continue
            kept += 1
            tasks.append({"adapter": "android", "source": f"screens/{path.name}", "goal": steps[i] if i < len(steps) else goal,
                          "episode_goal": goal, "expected_choice": ids, "target": target, "tap": [act["x"], act["y"]],
                          "action": act["action_type"], "review": "auto"})
        print(f"  episode {ep}: {kept} taps  {goal[:70]}", flush=True)
        if episodes >= args.episodes:
            break
    (HERE / args.tasks).write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    print(f"{len(tasks)} tasks from {episodes} episodes; skipped: {skipped}")


if __name__ == "__main__":
    main()
