"""jevbrief: clean, traceable state briefings for TypeSafe's Jev model."""

from .adapters import Adapter
from .adapters import get as get_adapter
from .briefing import Briefing, Decision, Extracted
from .facts import Fact, register_reasons
from .questions import FactChoice, OptionChoice, QuestionPack
from .rules import Boost, Drop, GroupRule, Rule, RuleSet


def __getattr__(name):
    if name == "Brief":  # the web shortcut; imported lazily so the core never loads the web adapter
        from .adapters.web import Brief

        return Brief
    if name in ("select_tools", "pick_tool"):  # the tools shortcuts, also lazy
        from .adapters import tools

        return getattr(tools, name)
    if name in ("check_progress", "loop_signals"):  # the steps shortcuts, also lazy
        from .adapters import steps

        return getattr(steps, name)
    raise AttributeError(name)


__all__ = ["Adapter", "Boost", "Brief", "Briefing", "Decision", "Drop", "Extracted", "Fact", "FactChoice",
           "GroupRule", "OptionChoice", "QuestionPack", "check_progress", "loop_signals", "pick_tool", "select_tools", "Rule", "RuleSet", "get_adapter", "register_reasons"]
__version__ = "0.7.0"
