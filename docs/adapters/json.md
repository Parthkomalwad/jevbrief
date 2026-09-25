# json adapter

Turns any JSON or JSON Lines data into facts with a small config file: support tickets, product catalogs, CRM records, API responses, search results. No code and no extra dependencies (on Python 3.10, TOML configs need `pip install "jevbrief[json]"`).

| | |
|---|---|
| **Reads** | Any JSON or JSON Lines data, mapped to facts by a small TOML or JSON config |
| **Jev answers** | Which item fits the goal, or which fixed action to take |
| **Install** | `pip install jevbrief`. On Python 3.10, TOML configs need `jevbrief[json]`. |
| **Main API** | `Briefing(JsonAdapter("config.toml"), goal)` and `--adapter json --config` |
| **Benchmark** | 9 synthetic queries: 100% against 89%, with 48% fewer tokens |

## Quick start

```bash
jevbrief inspect tickets.json --adapter json --config tickets.toml --goal "a customer was billed twice"
jevbrief ask     tickets.json --adapter json --config tickets.toml --goal "a customer was billed twice" --view
```

## Python

```python
from jevbrief import Briefing
from jevbrief.adapters.json import JsonAdapter

brief = Briefing(JsonAdapter("tickets.toml"), goal="a customer was billed twice", trace="traces/triage.jsonl")
brief.extract("tickets.json")          # or a Python list or dict
decision = brief.decide()
if decision.fact:
    print("open", decision.fact.id, decision.fact.label)
```

## Config reference

TOML or JSON. A full example is in [bench/json/tickets.toml](../../bench/json/tickets.toml).

| Key | Meaning | Example |
|---|---|---|
| `items` | Dotted path to the list of items. Omit when the data is the list | `"tickets"`, `"data.results"` |
| `id` | Template for a unique, stable ID. Omit to hash the item | `"{id}"` |
| `label` | Template for what a person would call it | `"{subject}"` |
| `kind` | Literal or template | `"ticket"`, `"{category}"` |
| `send` | Fields sent to Jev as-is | `["priority", "customer.tier"]` |
| `buckets` | Numbers or date ages turned into named values in code | see below |
| `match_fields` | Extra fields where goal words raise the score | `["tags", "body"]` |
| `required` | Items missing any of these are dropped as `json.missing_field` | `["id", "subject"]` |
| `rules` | Drop or boost rules, each a reason code `json.<name>` | see below |
| `question` | Instructions, option descriptions, and optional fixed options | see below |
| `context` | A string sent to Jev with the items | `"Queue for the billing team"` |
| `now` | Fixed "now" for date rules and buckets, for repeatable runs | `"2026-09-24T12:00:00Z"` |
| `keep_threshold` | Score below which kept items are dropped as `low_score` | `0.3` |

Templates use `{field}` and dotted paths such as `{customer.tier}`. Lists are joined with commas.

### Buckets

Jev is weak at comparing numbers and dates, so compute them into words:

```toml
[buckets.updated]          # attr name sent to Jev
field = "updated_at"
age = true                 # use the date's age in days
edges = [1, 7]
labels = ["today", "this week", "earlier"]

[buckets.price_range]
field = "price"
edges = [50, 150]
labels = ["budget", "mid-range", "premium"]
```

### Rules

```toml
[[rules]]
name = "closed"                       # reason code: json.closed
description = "The ticket is closed"  # shown in the viewer
drop_if = { field = "status", equals = "closed" }

[[rules]]
name = "vip"
description = "Kept: gold customer"
boost_if = { field = "customer.tier", in = ["gold", "platinum"] }
boost = 0.2
```

Operators: `equals`, `not_equals`, `in`, `not_in`, `greater_than`, `less_than`, `matches` (regular expression), `older_than_days`, `newer_than_days`, `missing` (true or false). Several operators in one condition must all hold.

### Question

```toml
[question]
instructions = "Goal: {goal}\nWhich one ticket in `items` should a support agent open for this goal?"
describe = "{subject} ({priority} priority)"   # option descriptions
none = "No ticket matches this goal"
```

The default pack, `choose_item`, is a Choice over the kept items plus "none". Add fixed options instead to choose an action:

```toml
[question.options]
refund = "Issue a refund"
escalate = "Escalate to a human"
reply = "Send the standard reply"
```

Add independent questions to the same call with `[question.extra.<id>]`, for example a Noul:

```toml
[question.extra.angry]
type = "noul"
instructions = "Is the customer angry?"
```

## Reason codes

| Code | Meaning |
|---|---|
| `json.<rule name>` | A config rule dropped (or boosted) it |
| `json.missing_field` | A `required` field is missing |
| `json.goal_match_fields` | Kept: a `match_fields` value shares a word with the goal |
| Core codes | `unlabeled`, `duplicate`, `low_score`, `budget` |

## Benchmark

[bench/json/results.md](../../bench/json/results.md): 9 tasks over a ticket queue and a product catalog. Raw 89% (24/27) at a median of 3,848 input tokens, jevbrief 100% (27/27) at 2,002. Synthetic data; see the caveats in the results file.

## Limits

- **A config is required.** Without one, the adapter cannot tell which list to read or what an item is called.
- **Rules are fixed.** Each rule compares one field. For relevance across many free-text items, the ranking in the [tools adapter](tools.md) shows the pattern to follow.
- **Synthetic benchmark.** See the caveats in the results file.
