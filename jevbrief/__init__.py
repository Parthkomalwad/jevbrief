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
    raise AttributeError(name)


__all__ = ["Adapter", "Boost", "Brief", "Briefing", "Decision", "Drop", "Extracted", "Fact", "FactChoice",
           "GroupRule", "OptionChoice", "QuestionPack", "Rule", "RuleSet", "get_adapter", "register_reasons"]
__version__ = "0.4.0"
