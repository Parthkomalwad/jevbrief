import json

from jevbrief import Briefing
from jevbrief.adapters.android import AndroidAdapter, parse_xml, position
from jevbrief.testing import FakeJev, check_adapter

# A settings screen, as `adb shell uiautomator dump` writes it (1080 x 2400).
DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.android.systemui" content-desc="" clickable="false" enabled="true" focusable="false" scrollable="false" bounds="[0,0][1080,80]">
    <node index="0" text="12:30" resource-id="com.android.systemui:id/clock" class="android.widget.TextView" package="com.android.systemui" content-desc="" clickable="true" enabled="true" focusable="true" scrollable="false" bounds="[40,10][160,70]" />
  </node>
  <node index="1" text="" resource-id="" class="android.widget.FrameLayout" package="com.example.settings" content-desc="" clickable="false" enabled="true" focusable="false" scrollable="false" bounds="[0,80][1080,2400]">
    <node index="0" text="Settings" resource-id="com.example.settings:id/title" class="android.widget.TextView" package="com.example.settings" content-desc="" clickable="false" enabled="true" focusable="false" scrollable="false" bounds="[40,100][600,180]" />
    <node index="1" text="Search settings" resource-id="com.example.settings:id/search_box" class="android.widget.EditText" package="com.example.settings" content-desc="" hint="Search settings" clickable="true" enabled="true" focusable="true" scrollable="false" bounds="[40,200][1040,300]" />
    <node index="2" text="" resource-id="com.example.settings:id/list" class="androidx.recyclerview.widget.RecyclerView" package="com.example.settings" content-desc="" clickable="false" enabled="true" focusable="false" scrollable="true" bounds="[0,320][1080,2200]">
      <node index="0" text="" resource-id="com.example.settings:id/row" class="android.widget.LinearLayout" package="com.example.settings" content-desc="" clickable="true" enabled="true" focusable="true" scrollable="false" bounds="[0,320][1080,480]">
        <node index="0" text="Wi-Fi" resource-id="android:id/title" class="android.widget.TextView" package="com.example.settings" content-desc="" clickable="false" enabled="true" focusable="false" scrollable="false" bounds="[40,340][600,400]" />
        <node index="1" text="Connected to Home" resource-id="android:id/summary" class="android.widget.TextView" package="com.example.settings" content-desc="" clickable="false" enabled="true" focusable="false" scrollable="false" bounds="[40,400][600,460]" />
      </node>
      <node index="1" text="" resource-id="com.example.settings:id/bluetooth_toggle" class="android.widget.Switch" package="com.example.settings" content-desc="Bluetooth" checkable="true" checked="false" clickable="true" enabled="true" focusable="true" scrollable="false" bounds="[880,500][1040,580]" />
      <node index="2" text="Airplane mode" resource-id="com.example.settings:id/airplane" class="android.widget.Button" package="com.example.settings" content-desc="" clickable="true" enabled="false" focusable="true" scrollable="false" bounds="[0,600][1080,760]" />
      <node index="3" text="Battery" resource-id="com.example.settings:id/battery" class="android.widget.Button" package="com.example.settings" content-desc="" clickable="true" enabled="true" focusable="true" scrollable="false" bounds="[0,2500][1080,2660]" />
      <node index="4" text="" resource-id="com.example.settings:id/divider_tap" class="android.view.View" package="com.example.settings" content-desc="Divider" clickable="true" enabled="true" focusable="false" scrollable="false" bounds="[0,780][1080,784]" />
      <node index="5" text="Hidden option" resource-id="com.example.settings:id/hidden" class="android.widget.Button" package="com.example.settings" content-desc="" clickable="true" enabled="true" focusable="true" scrollable="false" visible-to-user="false" bounds="[0,800][1080,960]" />
      <node index="6" text="" resource-id="com.example.settings:id/icon" class="android.widget.ImageView" package="com.example.settings" content-desc="" clickable="true" enabled="true" focusable="false" scrollable="false" bounds="[0,980][200,1100]" />
      <node index="7" text="Display" resource-id="com.example.settings:id/display" class="android.widget.Button" package="com.example.settings" content-desc="" clickable="true" enabled="true" focusable="true" scrollable="false" bounds="[0,1120][1080,1280]" />
      <node index="8" text="Display" resource-id="com.example.settings:id/display_again" class="android.widget.Button" package="com.example.settings" content-desc="" clickable="true" enabled="true" focusable="true" scrollable="false" bounds="[0,1300][1080,1460]" />
    </node>
    <node index="3" text="" resource-id="com.example.settings:id/password" class="android.widget.EditText" package="com.example.settings" content-desc="" hint="Wi-Fi password" password="true" clickable="true" enabled="true" focusable="true" scrollable="false" bounds="[40,2220][1040,2320]" />
  </node>
</hierarchy>"""


def brief(source, goal="Turn on Bluetooth"):
    b = Briefing(AndroidAdapter(), goal, trace=None, jev=FakeJev())
    b.extract(source)
    return b


def by_label(b):
    return {f.label: f for f in b.facts}


def test_contract(tmp_path):
    (tmp_path / "window_dump.xml").write_text(DUMP, encoding="utf-8")
    check_adapter(AndroidAdapter(), tmp_path / "window_dump.xml", goal="Turn on Bluetooth")


def test_system_ui():
    assert by_label(brief(DUMP))["12:30"].reason == "android.system_ui"


def test_offscreen():
    assert by_label(brief(DUMP))["Battery"].reason == "android.offscreen"


def test_decorative():
    assert by_label(brief(DUMP))["Divider"].reason == "android.decorative"  # 4 pixels tall


def test_not_interactive():
    b = by_label(brief(DUMP))
    assert b["Settings"].reason == "android.not_interactive" and b["Settings"].kind == "text"
    assert by_label(brief(DUMP, goal="open Settings"))["Settings"].kept  # text that mentions the goal is kept


def test_id_match():
    dump = DUMP.replace('text="Display" resource-id="com.example.settings:id/display"',
                        'text="Screen" resource-id="com.example.settings:id/display_brightness"')
    f = by_label(brief(dump, goal="change the display brightness"))["Screen"]
    assert f.kept and f.reason == "android.id_match"


def test_unlabeled_icon_is_dropped():
    f = next(f for f in brief(DUMP).facts if f.meta["rid"].endswith("/icon"))
    assert f.label == "" and f.reason == "unlabeled"


def test_core_rules():
    b = by_label(brief(DUMP))
    assert b["Airplane mode"].reason == "disabled"
    assert b["Hidden option"].reason == "hidden"
    assert [f.reason for f in brief(DUMP).facts if f.label == "Display"].count("duplicate") == 1


def test_facts_are_semantic_and_private():
    b = by_label(brief(DUMP))
    row = b["Wi-Fi · Connected to Home"]  # a clickable row is labeled by the text inside it
    assert row.kind == "button" and row.kept and row.attrs["position"] == "top"
    toggle = b["Bluetooth"]
    assert toggle.kind == "toggle" and toggle.attrs == {"position": "top right", "id": "bluetooth toggle", "checked": "no"}
    assert toggle.kept and toggle.reason == "goal_match"
    search = b["Search settings"]
    assert search.kind == "input" and search.attrs["filled"] == "no"
    password = b["Wi-Fi password"]
    assert password.attrs["password"] == "yes" and password.attrs["filled"] == "no"
    assert "Search settings" not in json.dumps(password.attrs)


def test_filled_input_never_sends_its_value():
    dump = DUMP.replace('text="Search settings" resource-id="com.example.settings:id/search_box"',
                        'text="my secret query" resource-id="com.example.settings:id/search_box"')
    b = brief(dump)
    search = next(f for f in b.facts if f.kind == "input" and "search" in f.meta["rid"])
    assert search.label == "Search settings" and search.attrs["filled"] == "yes"
    assert "secret" not in json.dumps(b.state())


def test_appium_page_source():
    appium = parse_xml(DUMP.replace("<node ", "<android.widget.View ").replace("</node>", "</android.widget.View>"))
    uia = parse_xml(DUMP)
    assert [(n["text"], n["box"], n["clickable"]) for n in appium] == [(n["text"], n["box"], n["clickable"]) for n in uia]
    appium_src = """<hierarchy><android.widget.Button text="OK" class="android.widget.Button" clickable="true"
        enabled="true" displayed="false" bounds="[0,0][100,100]"/></hierarchy>"""
    assert parse_xml(appium_src)[0]["visible"] is False


def test_android_world_ui_elements(tmp_path):
    elements = [
        {"text": "Bluetooth", "content_description": None, "class_name": "android.widget.Switch", "is_checkable": True,
         "is_checked": False, "is_clickable": True, "is_enabled": True, "is_visible": True,
         "bbox_pixels": {"x_min": 880, "y_min": 500, "x_max": 1040, "y_max": 580}, "package_name": "com.example.settings",
         "resource_name": "com.example.settings:id/bluetooth_toggle"},
        {"text": "Settings", "class_name": "android.widget.TextView", "is_clickable": False,
         "bbox_pixels": {"x_min": 40, "y_min": 100, "x_max": 600, "y_max": 180}},
        {"text": None, "content_description": "Navigate up", "class_name": "android.widget.ImageButton", "is_clickable": True,
         "bbox_pixels": {"x_min": 0, "y_min": 0, "x_max": 1080, "y_max": 2400}},
    ]
    (tmp_path / "ui.json").write_text(json.dumps(elements), encoding="utf-8")
    b = by_label(brief(tmp_path / "ui.json"))
    assert b["Bluetooth"].kind == "toggle" and b["Bluetooth"].kept
    assert b["Settings"].reason == "android.not_interactive" and b["Navigate up"].kind == "button"


def test_positions():
    assert [position(b, (1000, 3000)) for b in ([0, 0, 100, 100], [450, 1400, 550, 1600], [900, 2900, 1000, 3000])] \
        == ["top left", "center", "bottom right"]


def test_raw_arm_is_every_element_with_pixels():
    ex = AndroidAdapter().extract(DUMP)
    assert len(ex.raw) == 18 and ex.raw[0].attrs["bounds"] == [0, 0, 1080, 80]
    assert "my secret" not in json.dumps([f.label for f in ex.raw])


def test_screenshot_for_the_viewer(tmp_path):
    (tmp_path / "shot.png").write_bytes(b"\x89PNG fake")
    ex = AndroidAdapter().extract(DUMP, screenshot=tmp_path / "shot.png")
    assert ex.image == b"\x89PNG fake" and ex.image_size == (1080, 2400)
    assert ex.source["app"] == "com.example.settings"
