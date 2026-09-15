"""The types the pipeline passes around. All frozen, all serialisable.

Frozen because a critique that can be edited after the gate read it is not
evidence. Every one of these ends up in `state.json` or under `critiques/`, so
each carries ``to_dict`` and the arithmetic that interprets it lives on the
type rather than in whichever stage happens to need it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

__all__ = [
    "ChapterPlan",
    "ChapterRecord",
    "Critique",
    "Finding",
    "GateDecision",
    "Outline",
    "Usage",
]


@dataclass(frozen=True)
class Usage:
    """Tokens for one model call. Added up by the budget guard."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            model=self.model,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Finding:
    """One thing wrong with a draft, quoting the text that is wrong.

    ``quote`` is not decoration. A finding that says "continuity problem in
    chapter 2" cannot be acted on; one that quotes the drifted surname can be,
    and it is what :func:`novaforge.context.build_chapter_context` hands the
    writer on the rewrite.
    """

    kind: str
    severity: str
    quote: str
    fix: str
    reference: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Finding":
        return cls(
            kind=str(data.get("kind", "unknown")),
            severity=str(data.get("severity", "medium")),
            quote=str(data.get("quote", "")),
            fix=str(data.get("fix", "")),
            reference=str(data.get("reference", "")),
        )


@dataclass(frozen=True)
class Critique:
    """One critic's verdict on one draft."""

    critic: str
    score: int
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    detail: Mapping[str, Any] = field(default_factory=dict)

    def passed(self, threshold: int) -> bool:
        return self.score >= threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "critic": self.critic,
            "score": self.score,
            "findings": [f.to_dict() for f in self.findings],
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class GateDecision:
    """What the gate decided about one draft, and why.

    Written to the audit log as a ``gate_decision`` row, so the reason a
    chapter was accepted is reconstructable without rerunning anything.
    """

    chapter: int
    iteration: int
    scores: Mapping[str, int]
    threshold: int
    aggregate: str
    verdict: str  # accept | retry | accept_with_warnings | halt

    @property
    def score(self) -> int:
        """The aggregate. ``min`` is the default: a chapter is only as good as
        its worst critic, so one failing critic cannot be averaged away."""
        values = list(self.scores.values()) or [0]
        if self.aggregate == "mean":
            return round(sum(values) / len(values))
        return min(values)

    @property
    def accepted(self) -> bool:
        return self.verdict in ("accept", "accept_with_warnings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter": self.chapter,
            "iteration": self.iteration,
            "scores": dict(self.scores),
            "aggregate_score": self.score,
            "threshold": self.threshold,
            "aggregate": self.aggregate,
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class ChapterPlan:
    """One row of the outline: what this chapter must accomplish.

    This, the Story Bible and a capped rolling summary are the *entire* context
    the Chapter Writer receives (FLOW-4 ``context_policy``).
    """

    number: int
    title: str
    pov: str
    tension: int
    promise: str
    beats: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "pov": self.pov,
            "tension": self.tension,
            "promise": self.promise,
            "beats": list(self.beats),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChapterPlan":
        return cls(
            number=int(data["number"]),
            title=str(data.get("title", "")),
            pov=str(data.get("pov", "")),
            tension=int(data.get("tension", 5)),
            promise=str(data.get("promise", "")),
            beats=tuple(str(b) for b in data.get("beats", ())),
        )


@dataclass(frozen=True)
class Outline:
    """The whole outline: the plans plus the promises made to the reader."""

    plans: tuple[ChapterPlan, ...]
    promises: tuple[str, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.plans)

    def __iter__(self):
        return iter(self.plans)

    def plan_for(self, number: int) -> ChapterPlan:
        for plan in self.plans:
            if plan.number == number:
                return plan
        raise KeyError(f"no outline entry for chapter {number}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plans": [p.to_dict() for p in self.plans],
            "promises": list(self.promises),
        }


@dataclass(frozen=True)
class ChapterRecord:
    """The state of one chapter, as persisted in ``state.json``."""

    number: int
    status: str = "pending"  # pending | approved | accepted_with_warnings
    words: int = 0
    lines: int = 0
    iterations: int = 0
    scores: Mapping[str, int] = field(default_factory=dict)
    warnings: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "status": self.status,
            "words": self.words,
            "lines": self.lines,
            "iterations": self.iterations,
            "scores": dict(self.scores),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChapterRecord":
        return cls(
            number=int(data["number"]),
            status=str(data.get("status", "pending")),
            words=int(data.get("words", 0)),
            lines=int(data.get("lines", 0)),
            iterations=int(data.get("iterations", 0)),
            scores=dict(data.get("scores", {})),
            warnings=tuple(data.get("warnings", ())),
        )
