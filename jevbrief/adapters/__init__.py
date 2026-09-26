"""Adapters turn a source (web page, JSON file, game, logs, chat) into facts.

Built-in and third-party adapters register the same way, through the `jevbrief.adapters`
entry point group. A third-party package adds one line to its pyproject.toml:

    [project.entry-points."jevbrief.adapters"]
    mysource = "mypackage.adapter:MySourceAdapter"
"""

from __future__ import annotations

import inspect
from importlib import import_module
from importlib.metadata import entry_points
from typing import ClassVar

from ..briefing import Extracted
from ..facts import Fact, register_reasons
from ..questions import QuestionPack
from ..rules import RuleSet
from ..sources import load_config

GROUP = "jevbrief.adapters"
# Used when jevbrief runs from a source checkout without being installed.
BUILTIN = {"web": "jevbrief.adapters.web:WebAdapter", "json": "jevbrief.adapters.json:JsonAdapter",
           "otel": "jevbrief.adapters.otel:OtelAdapter", "nes": "jevbrief.adapters.nes:NesAdapter",
           "ci": "jevbrief.adapters.ci:CiAdapter",
           "tools": "jevbrief.adapters.tools:ToolsAdapter",
           "steps": "jevbrief.adapters.steps:StepsAdapter",
           "pr": "jevbrief.adapters.pr:PrAdapter"}


class Adapter:
    """Base class for adapters. Subclasses set the attributes and implement the methods below.

    The base constructor registers `reasons` and loads the config, so most adapters need no `__init__`.
    """

    name = "adapter"
    version = "1"
    renderer = "table"            # viewer layout: "spatial" (image + boxes), "timeline" (meta["view"] spans), or "table"
    extra = ""                    # the pip extra that installs this adapter's dependencies
    reasons: ClassVar[dict[str, str]] = {}  # adapter reason codes ("<name>.<code>") and descriptions
    takes_config: ClassVar[bool] = True     # False: `configure` rejects any config

    def __init__(self, config=None):
        register_reasons(self.reasons)
        self.config: dict = {}
        if config is not None:
            self.configure(config)

    def configure(self, config) -> None:
        """Load a config: a dict, or a path to a `.toml` or `.json` file."""
        if not self.takes_config:
            raise ValueError(f"the {self.name} adapter takes no config")
        self.config = load_config(config, self.extra)

    def settings(self, options: dict | None = None) -> dict:
        """The config with per-call options (keyword arguments to `extract`) on top."""
        return {**self.config, **(options or {})}

    def extract(self, source, **options) -> Extracted:
        """Read `source` and return facts plus a small context dict. Turn numbers into semantic values here.

        When the benchmark's raw arm needs more than the facts (for example raw log lines), set `Extracted.raw`.
        """
        raise NotImplementedError

    def rules(self, options: dict | None = None) -> RuleSet:
        """The rules, for this config plus the options passed to the latest `extract` (see `settings`)."""
        raise NotImplementedError

    def packs(self) -> dict[str, QuestionPack]:
        """Question packs, by name. The first one is the default."""
        raise NotImplementedError

    def state(self, goal: str, kept: list[Fact], source: dict) -> dict:
        """The state sent to Jev."""
        return {"goal": goal, "items": [f.state() for f in kept]}

    def raw(self, facts: list[Fact]) -> list[Fact]:
        """The facts a naive integration would send. Used by the benchmark's raw arm when `Extracted.raw` is unset."""
        return facts


def adapter_rules(adapter: Adapter, options: dict | None = None) -> RuleSet:
    """`adapter.rules(options)`, or `adapter.rules()` for adapters written before rules took options."""
    try:
        takes_options = bool(inspect.signature(adapter.rules).parameters)
    except (TypeError, ValueError):
        takes_options = False
    return adapter.rules(options) if takes_options else adapter.rules()


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
