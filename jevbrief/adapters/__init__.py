"""Adapters turn a source (web page, JSON file, game, logs, chat) into facts.

Built-in and third-party adapters register the same way, through the `jevbrief.adapters`
entry point group. A third-party package adds one line to its pyproject.toml:

    [project.entry-points."jevbrief.adapters"]
    mysource = "mypackage.adapter:MySourceAdapter"
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import entry_points

from ..briefing import Extracted
from ..facts import Fact
from ..questions import QuestionPack
from ..rules import RuleSet

GROUP = "jevbrief.adapters"
# Used when jevbrief runs from a source checkout without being installed.
BUILTIN = {"web": "jevbrief.adapters.web:WebAdapter", "json": "jevbrief.adapters.json:JsonAdapter",
           "otel": "jevbrief.adapters.otel:OtelAdapter", "nes": "jevbrief.adapters.nes:NesAdapter"}


class Adapter:
    """Base class for adapters. Subclasses set the attributes and implement the methods below."""

    name = "adapter"
    version = "1"
    renderer = "table"            # viewer layout: "spatial" (image + boxes), "timeline" (meta["view"] spans), or "table"
    extra = ""                    # the pip extra that installs this adapter's dependencies
    reasons: dict[str, str] = {}  # adapter reason codes ("<name>.<code>") and descriptions

    def configure(self, config) -> None:
        """Load an adapter config (a path or a dict). Adapters that take no config reject one."""
        raise ValueError(f"the {self.name} adapter takes no config")

    def extract(self, source, **options) -> Extracted:
        """Read `source` and return facts plus a small context dict. Turn numbers into semantic values here."""
        raise NotImplementedError

    def rules(self) -> RuleSet:
        raise NotImplementedError

    def packs(self) -> dict[str, QuestionPack]:
        """Question packs, by name. The first one is the default."""
        raise NotImplementedError

    def state(self, goal: str, kept: list[Fact], source: dict) -> dict:
        """The state sent to Jev."""
        return {"goal": goal, "items": [f.state() for f in kept]}

    def raw(self, facts: list[Fact]) -> list[Fact]:
        """The facts a naive integration would send. Used by the benchmark's raw arm."""
        return facts


def _load(target: str):
    module, _, attr = target.partition(":")
    return getattr(import_module(module), attr)


def available() -> dict[str, str]:
    """Adapter name -> import target, from entry points plus the built-ins."""
    found = {ep.name: ep.value for ep in entry_points(group=GROUP)}
    return {**BUILTIN, **found}


def get(name: str) -> Adapter:
    targets = available()
    if name not in targets:
        raise ValueError(f"unknown adapter {name!r}. Available: {', '.join(sorted(targets))}")
    return _load(targets[name])()


def need(extra: str, *modules: str) -> None:
    """Import check for an adapter's optional dependencies, with a clear install message."""
    for m in modules:
        try:
            import_module(m)
        except ImportError:
            raise ImportError(f'This adapter needs extra packages. Run: pip install "jevbrief[{extra}]"') from None
