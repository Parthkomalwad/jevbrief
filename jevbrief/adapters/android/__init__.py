"""The android adapter: a phone screen's UI elements to facts, for choosing the next tap.

Reads any of:
- `adb shell uiautomator dump` XML (`<hierarchy><node ... bounds="[0,0][1080,2400]">`)
- Appium page source (UiAutomator2): the same attributes, with class names as tags
- a JSON list of UI elements, as recorded by AndroidWorld and AndroidControl (`text`, `content_description`,
  `class_name`, `is_clickable`, `bbox_pixels`, ...)

Pass a path, the XML or JSON text, or parsed JSON. Standard library only.

Positions become words ("top left", "center", ...), and the text typed into a field is never sent: Jev sees
the field's hint and whether it is filled. Password fields are never read.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from ...briefing import Extracted
from ...facts import Fact, clean_label, fact_id
from ...questions import FactChoice
from ...rules import Boost, Drop, Rule, RuleSet, disabled, duplicate, goal_match, hidden, unlabeled
from .. import Adapter

NOT_INTERACTIVE = "android.not_interactive"
OFFSCREEN = "android.offscreen"
SYSTEM_UI = "android.system_ui"
DECORATIVE = "android.decorative"
ID_MATCH = "android.id_match"
REASONS = {
    NOT_INTERACTIVE: "Plain text that cannot be tapped and does not mention the goal",
    OFFSCREEN: "Outside the visible screen, or with no area",
    SYSTEM_UI: "Part of the status bar or other system UI, not the app",
    DECORATIVE: "Too small to be a real target (under 1% of the screen width or height)",
    ID_MATCH: "Kept: the resource ID shares a word with the goal",
}

SYSTEM_PACKAGES = {"com.android.systemui"}
BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
TRUE = {"true", "1", True}


def _flag(v) -> bool:
    return v in TRUE or str(v).lower() == "true"


def _short(cls: str) -> str:
    return (cls or "").rsplit(".", 1)[-1]


def _node(attrs: dict, cls: str, path: str, depth: int) -> dict:
    """One element in a common shape, from uiautomator or Appium XML attributes."""
    m = BOUNDS.match(attrs.get("bounds", "") or "")
    box = tuple(map(int, m.groups())) if m else None
    visible = attrs.get("visible-to-user", attrs.get("displayed", "true"))
    return {"text": attrs.get("text", "") or "", "desc": attrs.get("content-desc", "") or "",
            "hint": attrs.get("hint", "") or "", "id": attrs.get("resource-id", "") or "",
            "cls": cls or attrs.get("class", ""), "package": attrs.get("package", "") or "",
            "clickable": _flag(attrs.get("clickable")) or _flag(attrs.get("long-clickable")),
            "focusable": _flag(attrs.get("focusable")), "scrollable": _flag(attrs.get("scrollable")),
            "checkable": _flag(attrs.get("checkable")), "checked": _flag(attrs.get("checked")),
            "selected": _flag(attrs.get("selected")), "enabled": _flag(attrs.get("enabled", "true")),
            "password": _flag(attrs.get("password")), "visible": _flag(visible),
            "editable": "EditText" in (cls or attrs.get("class", "")) or _flag(attrs.get("editable")),
            "box": box, "path": path, "depth": depth}


def parse_xml(text: str) -> list[dict]:
    """Elements from `uiautomator dump` or Appium page source, in document order."""
    root = ET.fromstring(text)
    out: list[dict] = []

    def walk(el, path: str, depth: int, parent: int | None):
        for i, child in enumerate(el):
            cls = child.get("class") or ("" if child.tag == "node" else child.tag)
            n = _node(dict(child.attrib), cls, f"{path}/{i}", depth)
            n["parent"] = parent
            out.append(n)
            walk(child, n["path"], depth + 1, len(out) - 1)

    walk(root, "", 0, None)
    return out


def parse_elements(items: list[dict]) -> list[dict]:
    """Elements from an AndroidWorld or AndroidControl UI element list (a flat list, no nesting)."""
    out = []
    for i, e in enumerate(items):
        b = e.get("bbox_pixels") or e.get("bbox") or {}
        box: tuple[int, int, int, int] | None = None
        if isinstance(b, dict) and b:
            box = (int(b.get("x_min", 0)), int(b.get("y_min", 0)), int(b.get("x_max", 0)), int(b.get("y_max", 0)))
        elif isinstance(b, (list, tuple)) and len(b) == 4:
            box = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
        cls = e.get("class_name") or e.get("className") or ""
        out.append({"text": e.get("text") or "", "desc": e.get("content_description") or e.get("contentDescription") or "",
                    "hint": e.get("hint_text") or "", "id": e.get("resource_id") or e.get("resource_name") or "",
                    "cls": cls, "package": e.get("package_name") or "",
                    "clickable": bool(e.get("is_clickable") or e.get("is_long_clickable")),
                    "focusable": bool(e.get("is_focusable")), "scrollable": bool(e.get("is_scrollable")),
                    "checkable": bool(e.get("is_checkable")), "checked": bool(e.get("is_checked")),
                    "selected": bool(e.get("is_selected")), "enabled": e.get("is_enabled", True) is not False,
                    "password": False, "visible": e.get("is_visible", True) is not False,
                    "editable": bool(e.get("is_editable")) or "EditText" in cls,
                    "box": box, "path": f"/{i}", "depth": 0, "parent": None})
    return out


def read(source) -> list[dict]:
    """Elements from a path, XML or JSON text, or parsed JSON."""
    if isinstance(source, (list, dict)):
        data = source
    else:
        text = Path(source).read_text(encoding="utf-8") if not str(source).lstrip().startswith(("<", "[", "{")) \
            else str(source)
        if text.lstrip().startswith("<"):
            return parse_xml(text)
        data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("ui_elements") or data.get("elements") or data.get("accessibility_tree") or []
    return parse_elements(data)


def position(box, screen) -> str:
    """Where a box's center is, as words: "top left", "center", "bottom right", ..."""
    w, h = screen
    cx, cy = (box[0] + box[2]) / 2 / max(w, 1), (box[1] + box[3]) / 2 / max(h, 1)
    row = "top" if cy < 1 / 3 else "bottom" if cy > 2 / 3 else "middle"
    col = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else ""
    return "center" if row == "middle" and not col else f"{row} {col}".strip()


def screen_size(nodes: list[dict]) -> tuple[int, int]:
    """The screen's width and height: the extent of the top-level nodes of a hierarchy, or, for a flat
    element list, the largest element (usually the full-screen root). Elements below the screen do not count."""
    top = [n["box"] for n in nodes if n["box"] and n["depth"] == 0]
    if len(top) != len([n for n in nodes if n["box"]]):  # a hierarchy: use its roots
        return max(b[2] for b in top), max(b[3] for b in top)
    boxes = [n["box"] for n in nodes if n["box"]]
    if not boxes:
        return 1080, 2400
    big = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    return big[2], big[3]


def _kind(n: dict) -> str:
    cls = _short(n["cls"])
    if n["editable"]:
        return "input"
    if n["checkable"] or cls in ("Switch", "CheckBox", "RadioButton", "ToggleButton"):
        return "toggle"
    if n["clickable"]:
        return "button"
    if n["scrollable"]:
        return "list"
    if n["focusable"]:
        return "button"
    return "text"


def _inner_text(nodes: list[dict], i: int, limit: int = 2) -> str:
    """Text of the elements inside node i: how most list rows and cards are labeled."""
    found, prefix = [], nodes[i]["path"] + "/"
    for n in nodes[i + 1:]:
        if not n["path"].startswith(prefix):
            break
        t = n["text"] or n["desc"]
        if t and not n["editable"] and t not in found:
            found.append(t)
            if len(found) == limit:
                break
    return " · ".join(found)


def _id_words(rid: str) -> str:
    return rid.rsplit("/", 1)[-1].replace("_", " ") if rid else ""


class AndroidAdapter(Adapter):
    """Options (keyword arguments to `extract`):

    screen      (width, height) in pixels. Default: taken from the hierarchy's root, or the largest element
    screenshot  a PNG or JPEG (path or bytes) for the viewer
    """

    name = "android"
    version = "1"
    renderer = "spatial"
    extra = "android"
    reasons = REASONS
    takes_config = False

    def extract(self, source, screenshot: bytes | str | None = None, **options) -> Extracted:
        nodes = read(source)
        if not nodes:
            raise ValueError("no UI elements found. Expected uiautomator XML, Appium page source, "
                             "or a JSON list of UI elements")
        screen = tuple(options["screen"]) if options.get("screen") else screen_size(nodes)
        app = Counter(n["package"] for n in nodes if n["package"] and n["package"] not in SYSTEM_PACKAGES)
        package = app.most_common(1)[0][0] if app else ""

        facts: list[Fact] = []
        for i, n in enumerate(nodes):
            kind = _kind(n)
            if kind == "text" and not (n["text"] or n["desc"]):
                continue  # layout containers and images with nothing to say
            if kind == "input":
                label = n["hint"] or n["desc"] or _id_words(n["id"]) or (n["text"] if not n["password"] else "")
            else:
                label = n["text"] or n["desc"] or _inner_text(nodes, i) or n["hint"]
            box = n["box"]
            attrs: dict = {}
            if box:
                attrs["position"] = position(box, screen)
            if n["id"]:
                attrs["id"] = _id_words(n["id"])
            if kind == "input":
                attrs["filled"] = "yes" if n["text"] and n["text"] != n["hint"] and not n["password"] else "no"
                if n["password"]:
                    attrs["password"] = "yes"
            if kind == "toggle":
                attrs["checked"] = "yes" if n["checked"] else "no"
            if n["selected"]:
                attrs["selected"] = "yes"
            if kind == "list":
                attrs["scrollable"] = "yes"
            area = box and (box[2] - box[0]) * (box[3] - box[1])
            facts.append(Fact(
                id=fact_id("android", n["id"], _short(n["cls"]), n["path"]),
                kind=kind,
                label=clean_label(label),
                attrs=attrs,
                meta={"box": [box[0], box[1], box[2] - box[0], box[3] - box[1]] if box else None,
                      "order": (box[1], box[0]) if box else (10**9, i), "cls": n["cls"], "package": n["package"],
                      "rid": n["id"],
                      "offscreen": not box or not area or area <= 0 or box[2] <= 0 or box[3] <= 0
                      or box[0] >= screen[0] or box[1] >= screen[1],
                      "tiny": bool(box) and ((box[2] - box[0]) < screen[0] * 0.01 or (box[3] - box[1]) < screen[1] * 0.01),
                      "system": n["package"] in SYSTEM_PACKAGES},
                visible=n["visible"],
                enabled=n["enabled"],
            ))

        image = size = None
        if screenshot is not None:
            image = Path(screenshot).read_bytes() if isinstance(screenshot, (str, Path)) else screenshot
            size = screen
        name = Path(source).name if isinstance(source, (str, Path)) and not str(source).lstrip().startswith(("<", "[", "{")) \
            else "screen"
        return Extracted(facts, {"name": name, "app": package, "screen": list(screen), "elements": len(nodes)},
                         image, size, raw=_raw(nodes, screen))

    def rules(self, options: dict | None = None) -> RuleSet:
        def id_match(f, ctx):
            return f.meta["rid"] and not ctx.matches(f.label) and ctx.matches(_id_words(f.meta["rid"]))

        return RuleSet([
            hidden, disabled,
            Rule(SYSTEM_UI, lambda f, ctx: Drop(SYSTEM_UI) if f.meta["system"] else None),
            Rule(OFFSCREEN, lambda f, ctx: Drop(OFFSCREEN) if f.meta["offscreen"] else None),
            Rule(DECORATIVE, lambda f, ctx: Drop(DECORATIVE) if f.meta["tiny"] and f.kind != "text" else None),
            unlabeled,
            Rule(NOT_INTERACTIVE, lambda f, ctx: Drop(NOT_INTERACTIVE)
                 if f.kind == "text" and not ctx.matches(f.label) else None),
            goal_match,
            Rule(ID_MATCH, lambda f, ctx: Boost(0.25, ID_MATCH) if id_match(f, ctx) else None),
            duplicate,
        ])

    def packs(self):
        pack = FactChoice(
            "next_tap",
            "Goal: {goal}\nWhich one element from `elements` should be tapped next (or typed into, or scrolled) "
            "to make progress on this goal?",
            lambda f: f"{f.kind}: {f.label}" + (f" ({f.attrs['position']})" if f.attrs.get("position") else ""),
            none_text="None of these elements helps: go back, or scroll to find more",
        )
        return {pack.name: pack}

    def state(self, goal, kept, source):
        return {"goal": goal, "app": source.get("app", ""), "elements": [f.state() for f in kept]}


def _raw(nodes: list[dict], screen) -> list[Fact]:
    """What a naive integration sends: every element in the hierarchy with its raw attributes and pixel bounds."""
    out = []
    for i, n in enumerate(nodes):
        attrs = {"class": n["cls"], "bounds": list(n["box"]) if n["box"] else None, "resource_id": n["id"],
                 "clickable": n["clickable"], "enabled": n["enabled"]}
        if n["desc"]:
            attrs["content_desc"] = n["desc"]
        label = n["text"] if not (n["editable"] or n["password"]) else n["hint"]
        out.append(Fact(id=fact_id("android", n["id"], _short(n["cls"]), n["path"]), kind=_short(n["cls"]) or "node",
                        label=clean_label(label or n["desc"] or _short(n["cls"])), attrs=attrs, meta={"order": i}))
    return out
