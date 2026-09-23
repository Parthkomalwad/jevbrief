"""Generate the synthetic benchmark pages in fixtures/.

The pages imitate common site layouts with realistic noise: large navigation
menus, hidden mega-menu links, cookie banners, icon-only buttons, repeated
links, product grids, and long footers. Some goals share no words with the
correct element (for example "log in" vs "Sign in") so the benchmark is not
just keyword matching.

Run: python bench/make_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures"

CSS = """
body{font-family:system-ui,sans-serif;margin:0;color:#222}
header,footer{padding:12px 24px;background:#f3f3f3}
nav a,footer a{margin-right:12px}
main{padding:24px;max-width:960px}
.mega{display:none}
.spacer{height:2600px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.card{border:1px solid #ddd;padding:8px}
.banner{position:fixed;bottom:0;left:0;right:0;background:#222;color:#fff;padding:12px}
.sr{position:absolute;width:0;height:0;overflow:hidden}
"""


def nav(brand: str, links: list[str]) -> str:
    items = "".join(f'<a href="/{l.lower().replace(" ", "-")}">{l}</a>' for l in links)
    mega = "".join(f'<a href="/c/{i}">Category {i}</a>' for i in range(1, 16))
    return f"""<header>
<a href="/" aria-label="{brand} home"><svg width="80" height="20"></svg></a>
<nav>{items}</nav>
<div class="mega">{mega}</div>
<input type="search" placeholder="Search {brand}">
<button aria-label="Open menu"><svg width="16" height="16"></svg></button>
<button><svg width="16" height="16"></svg></button>
<a href="/help">Help</a> <a href="/account">My account</a>
</header>"""


def footer(extra: str = "") -> str:
    cols = ["About us", "Careers", "Press", "Investors", "Blog", "Affiliates", "Gift cards",
            "Accessibility", "Privacy policy", "Terms of service", "Cookie settings", "Sitemap",
            "Store locator", "Shipping info", "Returns", "Help center", "Contact us"]
    links = "".join(f'<a href="/{c.lower().replace(" ", "-")}">{c}</a>' for c in cols)
    social = "".join(f'<a href="https://social.example/{s}"><svg width="16" height="16"></svg></a>'
                     for s in ("x", "fb", "ig", "yt"))
    return f"""<div class="spacer"></div>
<footer><h3>Company</h3>{links}{social}{extra}
<select name="region"><option>United States</option><option>India</option></select>
<a href="/privacy-policy">Privacy policy</a></footer>"""


def cookie_banner(visible: bool = False) -> str:
    style = "" if visible else ' style="display:none"'
    return f"""<div class="banner"{style}><h4>We value your privacy</h4>
<button>Accept all</button><button>Reject non-essential</button><a href="/cookie-settings">Customize</a></div>"""


def page(title: str, body: str, brand="Example", links=None, footer_extra="", banner=False) -> str:
    links = links or ["New", "Women", "Men", "Kids", "Home", "Sale", "Brands", "Deals"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title><style>{CSS}</style></head>
<body>
{nav(brand, links)}
<main>
{body}
</main>
{footer(footer_extra)}
{cookie_banner(banner)}
</body></html>
"""


def grid(prefix: str, n: int, button: str) -> str:
    cards = "".join(
        f'<div class="card"><a href="/p/{prefix}{i}">{prefix.title()} item {i}</a>'
        f'<button>{button}</button><button aria-label="Save {prefix} item {i}"><svg width="12" height="12"></svg></button></div>'
        for i in range(1, n + 1))
    return f'<h2>You may also like</h2><div class="grid">{cards}</div>'


PAGES = {
    "shop_product.html": (page("Trail Runner 2", """
<a href="/">Home</a> / <a href="/men">Men</a> / <a href="/men/shoes">Shoes</a>
<h1>Trail Runner 2</h1><p>$129.00</p><a href="#reviews">4.6 stars (1,203 reviews)</a>
<label for="size">Size</label><select id="size" name="size"><option>8</option><option>9</option></select>
<label for="qty">Quantity</label><input id="qty" type="number" value="1">
<button>Add to cart</button><button disabled>Buy now with one click</button>
<button class="mega">Add to cart</button><button>Add to wishlist</button>
<a href="/size-guide">Size guide</a><a href="/size-guide">Size guide</a>
<a href="/shipping">Free shipping over $50</a>
""" + grid("shoe", 8, "Quick add")),
        "add this item to the cart", "Add to cart"),

    "login.html": (page("Sign in", """
<h1>Welcome back</h1>
<label for="em">Email address</label><input id="em" type="email" value="sam@example.com">
<label for="pw">Password</label><input id="pw" type="password" value="correct-horse">
<label><input type="checkbox"> Keep me signed in</label>
<a href="/forgot">Forgot your password?</a>
<button type="submit">Sign in</button>
<p>or</p><button>Continue with Google</button><button>Continue with Apple</button>
<h2>New here?</h2><a href="/register">Create an account</a>
""", brand="Accounts"), "log in to my account", "Sign in"),

    "cart.html": (page("Your cart", """
<h1>Shopping cart (2 items)</h1>
<div class="card"><a href="/p/1">Trail Runner 2</a><select name="q1"><option>1</option></select><button>Remove</button><button>Save for later</button></div>
<div class="card"><a href="/p/2">Wool socks</a><select name="q2"><option>1</option></select><button>Remove</button><button>Save for later</button></div>
<label for="promo">Promo code</label><input id="promo"><button>Apply</button>
<p>Subtotal $141.00</p>
<button>Proceed to checkout</button><button>Check out with PayPal</button>
<a href="/">Continue shopping</a>
""" + grid("deal", 6, "Add to cart")), "go to checkout and pay", "Proceed to checkout"),

    "docs_home.html": (page("Docs", """
<h1>Widget SDK documentation</h1>
<input type="search" placeholder="Search docs">
<ul>
<li><a href="/docs/intro">Introduction</a></li><li><a href="/docs/quickstart">Quickstart</a></li>
<li><a href="/docs/install">Installation</a></li><li><a href="/docs/config">Configuration</a></li>
<li><a href="/docs/api">API reference</a></li><li><a href="/docs/cli">CLI</a></li>
<li><a href="/docs/faq">FAQ</a></li><li><a href="/docs/changelog">Changelog</a></li>
<li><a href="/docs/migrate">Migration guide</a></li><li><a href="/docs/contrib">Contributing</a></li>
</ul>
<button>Copy</button><button aria-label="Toggle theme"><svg width="12" height="12"></svg></button>
<a href="https://github.example/widget">GitHub</a>
""", brand="Widget", links=["Docs", "Guides", "API", "Blog", "Community", "Pricing"]),
        "find out how to install the package", "Installation"),

    "settings.html": (page("Account settings", """
<h1>Settings</h1>
<a href="/settings/profile">Profile</a><a href="/settings/notifications">Notifications</a>
<a href="/settings/billing">Billing</a><a href="/settings/security">Security</a>
<h2>Profile</h2><label for="n">Display name</label><input id="n"><button>Save changes</button>
<h2>Security</h2><button>Change password</button><button>Set up two-factor authentication</button>
<button>Sign out of all devices</button>
<h2>Danger zone</h2><button>Delete account</button>
""", brand="Accounts"), "update my password", "Change password"),

    "news_article.html": (page("City council approves new park", """
<h1>City council approves new park</h1><p>By A. Reporter, 5 min read</p>
<button>Share</button><button>Save</button><button aria-label="Listen"><svg width="12" height="12"></svg></button>
<a href="/tags/city">City</a><a href="/tags/parks">Parks</a>
<h2>Most read</h2>""" + "".join(f'<a href="/story/{i}">Top story number {i}</a>' for i in range(1, 11)),
        brand="Daily", links=["World", "Politics", "Business", "Tech", "Science", "Sports", "Opinion", "Video"],
        footer_extra='<h3>Get the morning briefing</h3><input type="email" placeholder="Your email" value="sam@example.com"><button>Sign up</button>'),
        "subscribe to the email newsletter", "Sign up"),

    "flights.html": (page("Book flights", """
<h1>Where to next?</h1>
<button>Round trip</button><button>One way</button><button>Multi-city</button>
<label for="f">From</label><input id="f" placeholder="City or airport" value="Mumbai (BOM)">
<label for="t">To</label><input id="t" placeholder="City or airport" value="Tokyo (HND)">
<label for="d">Depart</label><input id="d" type="date" value="2026-10-10">
<label for="r">Return</label><input id="r" type="date" value="2026-10-20">
<select name="cabin"><option>Economy</option><option>Business</option></select>
<button>Search flights</button>
<h2>Popular destinations</h2>""" + "".join(f'<a href="/deal/{c}">Flights to {c}</a>' for c in
        ("Paris", "Tokyo", "Dubai", "London", "Bali", "New York")) + "<button>Explore deals</button>",
        brand="Skyway", links=["Flights", "Hotels", "Cars", "Packages", "Deals", "Trips"]),
        "look for available flights", "Search flights"),

    "search_results.html": (page("Results for running shoes", """
<h1>Results for "running shoes"</h1><p>1-24 of 312</p>
<select name="sort"><option>Featured</option><option>Price: low to high</option></select>
<button>Filter</button>
""" + grid("result", 12, "Add to cart") + """
<nav aria-label="pagination"><a href="?p=1">1</a><a href="?p=2">2</a><a href="?p=3">3</a>
<a href="?p=13">13</a><a href="?p=2" aria-label="Next page">Next</a></nav>
"""), "go to the next page of results", "Next page"),

    "cookie_consent.html": (page("Home", """
<h1>Spring collection is here</h1><a href="/new">Shop new arrivals</a><a href="/sale">Shop the sale</a>
""" + grid("spring", 8, "Quick add"), banner=True),
        "accept the cookies", "Accept all"),

    "support.html": (page("Help center", """
<h1>How can we help?</h1><input type="search" placeholder="Search help articles">
""" + "".join(f'<a href="/help/{t}">{t.replace("-", " ").capitalize()}</a>' for t in
        ("track-my-order", "returns-and-refunds", "payment-methods", "shipping-times", "change-my-order",
         "gift-cards", "account-issues", "product-care")) + """
<h2>Still need help?</h2><button>Chat with us</button><a href="mailto:help@example.com">Email us</a>
""", brand="Help"), "talk to a customer service agent", "Chat with us"),
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    tasks = []
    for name, (html, goal, expected) in PAGES.items():
        (OUT / name).write_text(html, encoding="utf-8")
        tasks.append({"fixture": f"../fixtures/{name}", "goal": goal, "expected_label": expected})
    (ROOT / "bench" / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(tasks)} fixtures to {OUT}")


if __name__ == "__main__":
    main()
