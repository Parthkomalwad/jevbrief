# android adapter

Chooses which element to tap next on an Android screen, from its UI element tree. Standard library only.

| | |
|---|---|
| **Reads** | `uiautomator dump` XML, Appium page source, or a UI element list (AndroidWorld, AndroidControl) |
| **Jev answers** | Which element to tap, type into, or scroll next |
| **Install** | `pip install jevbrief`. Standard library only. |
| **Main API** | `Briefing(AndroidAdapter(), goal)` and `--adapter android` |
| **Benchmark** | Real taps from Google's AndroidControl: 84% against 61% on fresh data, with 89% fewer tokens |

## Quick start

```bash
adb shell uiautomator dump /sdcard/window_dump.xml && adb pull /sdcard/window_dump.xml
jevbrief inspect window_dump.xml --adapter android --goal "Turn on Bluetooth"
jevbrief ask     window_dump.xml --adapter android --goal "Turn on Bluetooth" --view
```

## Python

```python
from jevbrief import Briefing
from jevbrief.adapters.android import AndroidAdapter

brief = Briefing(AndroidAdapter(), goal="Turn on Bluetooth", trace="traces/android.jsonl")
brief.extract("window_dump.xml", screenshot="screen.png")    # the screenshot is optional, for the viewer
decision = brief.decide()
if decision.fact:
    x, y, w, h = decision.fact.meta["box"]                     # pixels: tap the center
    device.click(x + w // 2, y + h // 2)
```

With Appium, pass `driver.page_source`. With AndroidWorld, pass the observation's UI elements as a list of dicts.

## Input

It reads:
- **`adb shell uiautomator dump` XML**: `<hierarchy><node text=... resource-id=... bounds="[0,0][1080,2400]">`
- **Appium page source** (UiAutomator2): the same attributes, with class names as tags
- **a JSON list of UI elements**, as recorded by AndroidWorld and AndroidControl: `text`, `content_description`, `class_name`, `is_clickable`, `bbox_pixels`, and so on. A dict with `ui_elements` and an optional `screen` (`[width, height]`) also works.

Pass a path, the XML or JSON text, or the parsed JSON.

## What Jev sees

One fact per element that can be tapped, typed into, toggled, or scrolled, plus text that mentions the goal.

| Attribute | Values |
|---|---|
| kind | `button`, `input`, `toggle`, `list`, or `text` |
| label | The text or content description. A clickable row with no text of its own is labeled by the text inside it ("Wi-Fi · Connected to Home"). An icon with neither uses its resource ID ("cancel image") |
| `position` | Where it is on the screen, as words: `top left`, `top`, `center`, `bottom right`, and so on |
| `id` | The resource ID as words: `com.app:id/search_button` becomes `search button` |
| `checked`, `selected` | For toggles and tabs |
| `filled`, `password` | For inputs |
| `scrollable` | For lists |

**Privacy:** the text typed into a field is never sent. Jev sees the field's hint and whether it is filled, and password fields are never read. The same holds for the raw arm of the benchmark.

## Reason codes

| Rule | Effect |
|---|---|
| `android.system_ui` | Drops the status bar and other system UI (`com.android.systemui`) |
| `android.offscreen` | Drops elements outside the screen, or with no area |
| `android.decorative` | Drops elements under 1% of the screen's width or height |
| `android.not_interactive` | Drops plain text that does not mention the goal |
| `goal_match` | +0.35 when the label shares a word with the goal |
| `android.id_match` | +0.25 when the resource ID shares a word with the goal |
| `duplicate` | Drops a second element with the same label **in the same position**, keeping the innermost. The same label elsewhere, such as each row's "More options", is a different target and is kept |
| Core | `hidden`, `disabled`, `unlabeled`, `low_score`, `budget` |

## Options

Keyword arguments to `extract()`:

```python
brief.extract("window_dump.xml", screen=(1080, 2400), screenshot="screen.png")
```

- `screen`: `(width, height)` in pixels. The default comes from the hierarchy's root, or the largest element.
- `screenshot`: PNG or JPEG bytes or a path, shown by the viewer with Jev's pick outlined.

## Question pack

`next_tap`: a Choice over the kept elements, plus "None of these elements helps: go back, or scroll to find more". It asks which element should be tapped, typed into, or scrolled next.

## Benchmark

[bench/android/results.md](../../bench/android/results.md) uses real screens and taps from Google's [AndroidControl](https://github.com/google-research/google-research/tree/master/android_control) dataset (Apache 2.0). The goal is the recorded step instruction, such as "Click on the search icon", and the right answer is the element the person tapped. There were 3 runs per task.

| Set | Arm | Accuracy | Median input tokens |
|---|---|---|---|
| Tuning data: 107 taps | raw (every element) | 55% | 17,308 |
| | jevbrief | 85% | 1,813 |
| **Fresh data, adapter unchanged: 105 taps** | raw (every element) | 61% | 18,753 |
| | **jevbrief** | **84%** | **2,049** |

On about 1 screen in 10, the full element list was over Jev's token limit, and the raw arm failed. On screens that fit, raw scored 64% and 66%. Taking the rules' top element with no Jev call scored 37% and 32%.

To rebuild the sets, run `python bench/android/fetch_androidcontrol.py --episodes 40`, and add `--shard 1 --tasks tasks_shard1.json` for the holdout. The collector streams one dataset file with the standard library, and the labels need a hand review.

## Limits

- **The benchmark measures finding the element, not planning.** Each goal is a step instruction that names the element. With only the task's overall goal, choosing the next tap also needs the steps taken so far.
- **Identical controls in rows close together can't be told apart.** Position words are coarse (a 3 by 3 grid), so two neighboring rows' identical "More options" buttons look the same to Jev.
- **Unlabeled elements are dropped.** On fresh data, 8% of taps were on elements with no text, no description, no ID, and nothing inside. A screenshot-based model would be needed for those.
- **The recorded flags are trusted.** An element marked hidden or disabled is dropped, even when the flag is stale.
