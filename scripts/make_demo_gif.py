"""Build docs/assets/demo.gif from a real run on the demo shop.

Frames: the raw page, what jevbrief dropped, Jev's pick, the click, the next pick,
and the trace viewer. Every decision is a real Jev call.

Needs Pillow (dev only, not a jevbrief dependency):  pip install pillow
Run:  python scripts/make_demo_gif.py
"""

import io
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jevbrief import Brief  # noqa: E402
from jevbrief.cli import load_env  # noqa: E402
from jevbrief.viewer import open_viewer  # noqa: E402

OUT = ROOT / "docs" / "assets" / "demo.gif"
TRACE = ROOT / "traces" / "demo_gif.jsonl"
W, H, BAR = 1280, 720, 64
PINK, BLUE, GREY = (255, 63, 210), (40, 120, 255), (90, 90, 90)


def font(size):
    for name in ("consola.ttf", "CascadiaMono.ttf", "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def frame(png: bytes, caption: str, boxes=()):
    img = Image.open(io.BytesIO(png)).convert("RGB").resize((W, H - BAR))
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    sx, sy = W / 1280, (H - BAR) / 800
    for f, style in boxes:
        if not f.box:
            continue
        x, y, w, h = f.box
        r = [x * sx - 3, y * sy - 3, (x + w) * sx + 3, (y + h) * sy + 3]
        if style == "pick":
            d.rectangle(r, outline=PINK + (255,), width=5, fill=PINK + (40,))
            d.rectangle([r[0], r[1] - 26, r[0] + 118, r[1]], fill=PINK + (255,))
            d.text((r[0] + 6, r[1] - 23), "Jev's pick", font=font(18), fill="white")
        elif style == "kept":
            d.rectangle(r, outline=BLUE + (220,), width=2)
        else:
            d.rectangle(r, outline=GREY + (255,), width=1, fill=(0, 0, 0, 110))
    img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
    canvas = Image.new("RGB", (W, H), (27, 27, 27))
    canvas.paste(img, (0, 0))
    ImageDraw.Draw(canvas).text((24, H - BAR + 18), caption, font=font(26), fill=(242, 242, 242))
    return canvas


def main():
    load_env(ROOT / ".env")
    TRACE.unlink(missing_ok=True)
    frames, durations = [], []

    def add(img, ms):
        frames.append(img.quantize(colors=128, method=Image.Quantize.MEDIANCUT))
        durations.append(ms)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto((ROOT / "examples" / "demo_shop.html").as_uri())

        for goal in ("add this item to the cart", "go to checkout"):
            brief = Brief(goal=goal, trace=str(TRACE))
            brief.from_page_sync(page)
            shot = page.screenshot()
            dropped = [(f, "dropped") for f in brief.facts if not f.kept]
            kept = [(f, "kept") for f in brief.kept]
            add(frame(shot, f'Goal: "{goal}"'), 1400)
            add(frame(shot, f"jevbrief drops {len(dropped)} of {len(brief.facts)} elements, each with a reason",
                      dropped + kept), 2200)
            d = brief.next_click()
            add(frame(shot, f"Jev picks '{d.fact.label}' with confidence {d.confidence:.2f}",
                      kept + [(d.fact, "pick")]), 2200)
            page.locator(d.fact.selector).click()

        add(frame(page.screenshot(), "Done. Every decision is in the trace."), 1400)

        viewer = open_viewer(TRACE, open_browser=False)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, offline=True)
        ctx.add_init_script("localStorage.setItem('jevbrief-help-seen', '1')")
        vp = ctx.new_page()
        vp.goto(Path(viewer).as_uri())
        add(frame(vp.screenshot(), "jevbrief view: what Jev was told, what it wasn't, and why"), 3200)
        vp.evaluate("[...document.querySelectorAll('.card h2')].pop().scrollIntoView()")
        add(frame(vp.screenshot(), "Every dropped element is grouped by reason code"), 3000)
        browser.close()

    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
