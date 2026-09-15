"""The engine interface.

One call shape for every stage and every backend. A :class:`Request` carries
both the prose prompt *and* a structured ``task``:

* the Anthropic engine sends ``system`` and ``prompt`` and ignores ``task``;
* the mock engine reads ``task`` and ignores the prose.

That seam is what makes the mock deterministic without making it a different
pipeline. The stages build one Request either way, so nothing about stage code
changes between a free run and a paid one - and the audit log records the same
fields for both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from ..domain.models import Usage

__all__ = ["Completion", "Engine", "EngineError", "Request"]


class EngineError(RuntimeError):
    """The engine could not produce a completion."""


@dataclass(frozen=True)
class Request:
    """One call to a model."""

    role: str
    system: str
    prompt: str
    task: Mapping[str, Any] = field(default_factory=dict)
    max_tokens: int = 4096
    temperature: float = 1.0

    @property
    def kind(self) -> str:
        """What is being asked for - ``world``, ``chapter``, ``synopsis``..."""
        return str(self.task.get("kind", "text"))


@dataclass(frozen=True)
class Completion:
    """What came back, plus what it cost."""

    text: str
    usage: Usage
    model: str
    stop_reason: str = "end_turn"

    @property
    def truncated(self) -> bool:
        """The model hit the token ceiling mid-sentence.

        Worth checking rather than assuming: a chapter cut off at max_tokens
        fails the Length Critic for the wrong reason, and the useful fix is a
        bigger ceiling, not a rewrite.
        """
        return self.stop_reason == "max_tokens"


@runtime_checkable
class Engine(Protocol):
    """Anything the orchestrator can generate text with."""

    name: str
    model: str

    def complete(self, request: Request) -> Completion:
        """Produce a completion for ``request``."""
        ...
