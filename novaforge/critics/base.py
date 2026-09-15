"""What every critic is handed, and what every critic must return.

A critic gets the draft plus the canon it is judged against, and returns a
:class:`~novaforge.domain.models.Critique`: a score out of ten and findings,
each quoting the text it objects to.

The quote is not decoration. It is what
:func:`novaforge.context.build_chapter_context` hands the writer on the
rewrite, so a finding that cannot quote the problem cannot be acted on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from ..domain.models import Critique
from ..textops import Character

__all__ = ["Critic", "CriticContext", "score_from_findings"]


@dataclass(frozen=True)
class CriticContext:
    """Everything a critic may look at.

    Note what is *not* here: prior chapters' prose. A continuity critic that
    read every earlier chapter would be doing the job the Story Bible exists to
    do, and the run would get quadratically slower for it.
    """

    chapter: int
    text: str
    characters: tuple[Character, ...] = field(default_factory=tuple)
    world_rules: tuple[str, ...] = field(default_factory=tuple)
    config: Mapping[str, Any] = field(default_factory=dict)
    plan: Any = None

    def bands(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)


@runtime_checkable
class Critic(Protocol):
    """Judges one draft."""

    name: str

    def review(self, context: CriticContext) -> Critique:
        ...


def score_from_findings(findings: Sequence[Any], *, start: int = 10) -> int:
    """Turn findings into a score out of ten.

    Weighted by severity, floored at zero. A ``high`` finding costs enough on
    its own to drop a draft below a threshold of 8, because a contradiction of
    canon is not something three clean paragraphs make up for.
    """
    cost = {"high": 4, "medium": 2, "low": 1}
    total = start - sum(cost.get(getattr(f, "severity", "medium"), 2) for f in findings)
    return max(0, min(10, total))
