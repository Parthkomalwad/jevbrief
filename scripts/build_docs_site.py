"""Build the documentation site: one HTML page from the Markdown in docs/, styled like the trace viewer.

The Markdown files stay the source of truth. This script embeds them, rewrites links between them into
in-page routes, and copies the images they use. The page renders the Markdown in the browser.

Run:  python scripts/build_docs_site.py            # writes site/index.html and site/assets/
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site"
REPO = "https://github.com/parthkomalwad/jevbrief"
sys.path.insert(0, str(ROOT))
from jevbrief import __version__  # noqa: E402

# (route, nav label, section, source file, one-line summary shown in the nav)
PAGES = [
    ("home", "Overview", "Start", "docs/README.md", "What jevbrief does and where everything is"),
    ("python", "Python API", "Start", "docs/reference/python.md", "Briefing, Decision, select_tools, pick_tool"),
    ("cli", "Command line", "Start", "docs/reference/cli.md", "inspect, ask, view, bench, adapters"),
    ("tools", "tools", "Adapters", "docs/adapters/tools.md", "Which tool an agent calls next"),
    ("ci", "ci", "Adapters", "docs/adapters/ci.md", "Which error broke the build"),
    ("otel", "otel", "Adapters", "docs/adapters/otel.md", "Which log group explains an incident"),
    ("json", "json", "Adapters", "docs/adapters/json.md", "Which item fits the goal"),
    ("web", "web", "Adapters", "docs/adapters/web.md", "Which element to click next"),
    ("nes", "nes", "Adapters", "docs/adapters/nes.md", "Which move to make next"),
    ("build", "Build an adapter", "Guides", "ADAPTERS.md", "Facts, rules, packs, the contract test"),
]
ROUTES = {src: route for route, _, _, src, _ in PAGES}
LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")


def slug(text: str) -> str:
    """GitHub's heading anchors: lowercase, punctuation removed, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def rewrite(md: str, src: str, route: str, assets: set[str]) -> str:
    """Point links at in-page routes (`#page` or `#page.anchor`), images at site/assets, the rest at GitHub."""
    base = Path(src).parent

    def fix(m):
        bang, text, url = m.groups()
        path, _, anchor = url.partition("#")
        gh = re.match(rf"{re.escape(REPO)}/(?:blob|tree)/main/(.*)", path, re.I)
        if gh:
            target = gh.group(1)
        elif path.startswith(("http:", "https:", "mailto:")):
            return m.group(0)
        elif path:
            target = (base / path).as_posix()
            target = str(Path(target).resolve().relative_to(ROOT).as_posix()) if (ROOT / target).exists() else target
        else:
            return f"{bang}[{text}](#{route}.{anchor})"  # an anchor on this page
        if bang:  # an image: ship it with the site
            assets.add(target)
            return f"![{text}](assets/{Path(target).name})"
        if target in ROUTES:
            return f"[{text}](#{ROUTES[target]}{'.' + anchor if anchor else ''})"
        kind = "tree" if (ROOT / target).is_dir() else "blob"
        return f"[{text}]({REPO}/{kind}/main/{target}{'#' + anchor if anchor else ''})"

    return LINK.sub(fix, md)


def main() -> None:
    assets: set[str] = set()
    pages = []
    for route, label, section, src, summary in PAGES:
        md = (ROOT / src).read_text(encoding="utf-8")
        pages.append({"route": route, "label": label, "section": section, "src": src, "summary": summary,
                      "md": rewrite(md, src, route, assets)})
    for img in ("docs/assets/pipeline.svg", "docs/assets/benchmarks.svg", "docs/assets/adapters.svg"):
        assets.add(img)  # used by the overview's header

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    for a in sorted(assets):
        if (ROOT / a).exists():
            shutil.copy(ROOT / a, OUT / "assets" / Path(a).name)
        else:
            print(f"missing image: {a}")
    template = (Path(__file__).parent / "docs_site.html").read_text(encoding="utf-8")
    data = json.dumps({"version": __version__, "repo": REPO, "pages": pages}, ensure_ascii=False)
    html = template.replace("__DOCS__", data.replace("</", "<\\/"))
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"site/index.html: {len(pages)} pages, {len(assets)} images, {len(html) // 1024} KB")


if __name__ == "__main__":
    main()
