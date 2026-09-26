"""The web adapter: Playwright pages to facts. Install with: pip install "jevbrief[web]"."""

from __future__ import annotations

from pathlib import Path

from ...briefing import Briefing, Decision, Extracted
from ...facts import Fact, register_reasons
from ...questions import FactChoice
from .. import Adapter, need
from . import dom
from .rules import REASONS, web_rules

VIEWPORT = {"width": 1280, "height": 800}


def describe(f: Fact) -> str:
    extra = ", ".join(f"{k}={v}" for k, v in f.attrs.items() if k in ("type", "href_path", "filled"))
    return f"{f.kind}: {f.label}" + (f" ({extra})" if extra else "")


NEXT_CLICK = FactChoice(
    "next_click",
    "Goal: {goal}\nWhich one element from `elements` should be clicked or focused next to make progress on this goal?",
    describe,
    none_text="None of these elements helps with the goal",
)


def to_url(target: str) -> str:
    p = Path(target)
    return p.resolve().as_uri() if p.exists() else target


class WebAdapter(Adapter):
    name = "web"
    version = "1"
    renderer = "spatial"
    extra = "web"
    reasons = REASONS

    def __init__(self):
        register_reasons(REASONS)

    def rules(self):
        return web_rules()

    def packs(self):
        return {"next_click": NEXT_CLICK}

    def state(self, goal, kept, source):
        return {"goal": goal, "url": source.get("url", ""), "elements": [f.state() for f in kept]}

    def raw(self, facts):
        return [f for f in facts if f.kind != "text"]

    def extract(self, source, screenshot: bool = True, **options) -> Extracted:
        """Open `source` (URL or local HTML file) in headless Chromium and extract it."""
        need("web", "playwright")
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport=VIEWPORT)  # type: ignore[arg-type]  # a plain dict is what Playwright accepts
                page.goto(to_url(str(source)), wait_until="load")
                return self.from_page_sync(page, screenshot)
            finally:
                browser.close()

    def from_page_sync(self, page, screenshot: bool = True) -> Extracted:
        facts = dom.extract_sync(page)
        jpg = page.screenshot(type="jpeg", quality=55) if screenshot else None
        return self._extracted(facts, page, jpg)

    async def from_page(self, page, screenshot: bool = True) -> Extracted:
        facts = await dom.extract(page)
        jpg = await page.screenshot(type="jpeg", quality=55) if screenshot else None
        return self._extracted(facts, page, jpg)

    @staticmethod
    def _extracted(facts, page, jpg) -> Extracted:
        size = page.viewport_size or VIEWPORT
        return Extracted(facts, {"url": page.url, "viewport_h": size["height"]}, jpg, (size["width"], size["height"]))


class Brief(Briefing):
    """Web shortcut: `Brief(goal)`, then `from_page(page)` and `next_click()`."""

    def __init__(self, goal: str, *, screenshot: bool = True, **kw):
        super().__init__(WebAdapter(), goal, images=screenshot, **kw)

    async def from_page(self, page) -> list[Fact]:
        """Extract facts from an async Playwright page, then filter and budget them."""
        return self.load_extracted(await self.adapter.from_page(page, self._want_image))

    def from_page_sync(self, page) -> list[Fact]:
        """Same as `from_page`, for a sync Playwright page."""
        return self.load_extracted(self.adapter.from_page_sync(page, self._want_image))

    def next_click(self) -> Decision:
        """Ask Jev which element to click next."""
        return self.decide()

    @property
    def _want_image(self) -> bool:
        return self.images and self.trace_level != "off"
