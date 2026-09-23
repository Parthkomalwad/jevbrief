"""Generate the json adapter benchmark data: a support ticket queue and a product catalog.

The data is synthetic and deterministic. Goals are worded differently from the matching
item (for example "billed twice" vs "Charged two times"), and the queue holds closed,
spam, and stale look-alikes that the config rules should drop.

Run: python bench/json/make_data.py
"""

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOW = "2026-09-24T12:00:00Z"
rng = random.Random(7)

FILLER = [
    "How do I change my avatar?", "Feature request: dark mode for reports", "Question about API rate limits",
    "Where can I find the invoice PDF?", "Invite teammates to workspace", "Change billing email address",
    "Timezone shows wrong on calendar", "Integrate with Zapier?", "Delete old projects in bulk",
    "Keyboard shortcuts list", "Notification emails too frequent", "How to archive a board",
    "Upgrade from Pro to Team plan", "Two factor code not arriving by SMS", "Webhook retries documentation",
    "Mobile app crashes on Android 15", "Custom domain setup help", "Slow search in large workspaces",
    "Translate interface to German", "Onboarding checklist missing", "Can I pause my subscription?",
    "SSO with Okta configuration", "Import from Trello", "Printing a board looks cut off",
]
TIERS = ["free", "pro", "team", "enterprise"]


def ticket(i, subject, status="open", priority="normal", tier="pro", days_ago=2, tags=(), spam=False, body=""):
    day = 24 - days_ago if days_ago < 24 else 1
    month = "09" if days_ago < 24 else "06" if days_ago > 60 else "08"
    return {"id": f"t-{i}", "subject": subject, "body": body or subject, "status": status, "priority": priority,
            "customer": {"name": f"Customer {i}", "tier": tier}, "updated_at": f"2026-{month}-{day:02d}T09:00:00Z",
            "tags": list(tags), "spam": spam}


def tickets():
    items, n = [], 100
    targets = [
        ("Charged two times for September", dict(priority="high", tags=["billing"])),
        ("Login loop after password reset", dict(priority="high", tags=["auth"])),
        ("Dashboard shows 502 errors for everyone", dict(priority="urgent", tier="enterprise", tags=["outage"])),
        ("Package arrived broken, I want my money back", dict(tags=["orders"])),
        ("CSV download gives an empty file", dict(tags=["export"])),
        ("Cannot remove a former employee from our account", dict(tier="team", tags=["admin"])),
    ]
    decoys = [  # look-alikes the rules should drop
        ("Charged two times last year", dict(status="closed", tags=["billing"])),
        ("Login loop after password reset", dict(status="closed", tags=["auth"])),
        ("Dashboard shows 502 errors", dict(status="closed", tier="free", tags=["outage"])),
        ("Get your money back fast!!! click here", dict(spam=True)),
        ("CSV download broken", dict(days_ago=90, tags=["export"])),
        ("Cheap followers for your account", dict(spam=True)),
    ]
    for subject, kw in targets + decoys:
        items.append(ticket(n, subject, **kw))
        n += 1
    for subject in FILLER:
        items.append(ticket(n, subject, status=rng.choice(["open", "open", "pending", "closed"]),
                            priority=rng.choice(["low", "normal", "normal", "high"]), tier=rng.choice(TIERS),
                            days_ago=rng.choice([0, 1, 3, 10, 20, 90])))
        n += 1
    rng.shuffle(items)
    return {"exported_at": NOW, "tickets": items}


def catalog():
    base = [
        ("Trailhead waterproof rain jacket", "jackets", 129, True),
        ("Trailhead waterproof rain jacket XL", "jackets", 129, False),
        ("Summit down parka", "jackets", 349, True),
        ("City softshell jacket", "jackets", 99, True),
        ("Ultralight 2-person tent", "tents", 289, True),
        ("Family cabin tent 6-person", "tents", 419, True),
        ("Budget dome tent", "tents", 79, False),
        ("Merino hiking socks 3-pack", "socks", 32, True),
        ("Cotton crew socks 10-pack", "socks", 18, True),
        ("Insulated steel water bottle 1L", "bottles", 35, True),
        ("Collapsible silicone bottle", "bottles", 22, True),
        ("Trail running shoes", "shoes", 139, True),
        ("Leather hiking boots", "shoes", 219, True),
        ("Kids rain boots", "shoes", 39, True),
        ("Headlamp 400 lumen", "lights", 45, True),
        ("Camp lantern rechargeable", "lights", 59, False),
    ]
    items = [{"sku": f"sku-{i:03d}", "name": n, "category": c, "price": p, "in_stock": s,
              "rating": round(rng.uniform(3.2, 4.9), 1)} for i, (n, c, p, s) in enumerate(base, 1)]
    rng.shuffle(items)
    return {"products": items}


TASKS = [
    ("tickets.json", "tickets.toml", "a customer was billed twice this month", "t-100"),
    ("tickets.json", "tickets.toml", "someone keeps getting sent back to the sign-in page after changing their password", "t-101"),
    ("tickets.json", "tickets.toml", "a big customer says the app is down", "t-102"),
    ("tickets.json", "tickets.toml", "refund for a damaged order", "t-103"),
    ("tickets.json", "tickets.toml", "the spreadsheet export is not working", "t-104"),
    ("tickets.json", "tickets.toml", "take away access for someone who left the company", "t-105"),
    ("catalog.json", "catalog.toml", "something to keep me dry on a rainy hike", "Trailhead waterproof rain jacket"),
    ("catalog.json", "catalog.toml", "a light shelter for two people backpacking", "Ultralight 2-person tent"),
    ("catalog.json", "catalog.toml", "warm socks for long walks", "Merino hiking socks 3-pack"),
]


if __name__ == "__main__":
    (HERE / "tickets.json").write_text(json.dumps(tickets(), indent=1) + "\n", encoding="utf-8")
    (HERE / "catalog.json").write_text(json.dumps(catalog(), indent=1) + "\n", encoding="utf-8")
    tasks = []
    for data, config, goal, expected in TASKS:
        t = {"adapter": "json", "source": data, "config": config, "goal": goal}
        t["expected_choice" if expected.startswith("t-") else "expected_label"] = expected
        tasks.append(t)
    (HERE / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    print(f"wrote tickets.json, catalog.json, tasks.json ({len(tasks)} tasks) to {HERE}")
