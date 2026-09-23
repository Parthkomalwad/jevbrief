from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from jevbrief import Brief  # noqa: E402

PAGE = Path(__file__).parent / "pages" / "shop.html"


def test_from_page_sync_extracts_filters_and_screenshots():
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(PAGE.resolve().as_uri())
        brief = Brief("add this item to the cart", trace=None)
        brief.from_page_sync(page)
        browser.close()
    assert "Add to cart" in {f.label for f in brief.kept}
    assert all(f.reason for f in brief.facts if not f.kept)
    assert brief.page_image["image"].startswith("data:image/jpeg;base64,")
