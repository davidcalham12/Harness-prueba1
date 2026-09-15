"""The critic registry - the map from a gate's critic *kind* to code.

``specs/flow.yaml`` names critics by kind (``continuity``, ``science``,
``length``), not by agent role, because one of them is not an agent at all:
the Length Critic is arithmetic. Naming it alongside the other two in the gate
is the point - the gate does not care whether a verdict came from a model or
from ``len(text.split())``, only that it is a score with findings attached.

Adding a critic is one class and one registry entry, plus its name in
``quality_gate.critics``. No orchestrator change.
"""

from __future__ import annotations

from typing import Mapping

from .base import Critic, CriticContext
from .chatter import ChatterCritic
from .continuity import ContinuityCritic
from .length import LengthCritic
from .science import ScienceCritic

__all__ = ["Critic", "CriticContext", "CRITICS", "build_critics", "UnknownCritic"]


class UnknownCritic(KeyError):
    """The gate names a critic with no implementation."""


CRITICS: Mapping[str, type[Critic]] = {
    "chatter": ChatterCritic,
    "continuity": ContinuityCritic,
    "science": ScienceCritic,
    "length": LengthCritic,
}


def build_critics(names) -> tuple[Critic, ...]:
    """Instantiate the critics a gate asks for, in the order it asks for them.

    An unknown name raises. Skipping it would mean a typo in the config
    silently removes a critic from the gate - the gate would still pass, and it
    would be measuring less than it says it measures.
    """
    built = []
    for name in names:
        key = str(name).strip().lower()
        if key not in CRITICS:
            raise UnknownCritic(
                f"no critic named {key!r}; registered: {sorted(CRITICS)}"
            )
        built.append(CRITICS[key]())
    return tuple(built)
