"""What a stage is handed, and what it gives back.

A stage never constructs its own collaborators. The workspace, the Bible, the
engine and the reporter all arrive in :class:`StageContext`, which is what lets
a stage be run in a test against an in-memory workspace and a stub engine
without touching the orchestrator.

The agent arrives already resolved, so a stage never looks up its own prompt:
the orchestrator reads the role from the spec and hands over the matching
:class:`~novaforge.agents.Agent`. A stage that chose its own agent could
choose one the spec did not authorise.

The Bible arrives already narrowed: :class:`~novaforge.bible.FileBible` for the
two stages the spec declares ``writes_bible``, and
:class:`~novaforge.bible.ReadOnlyBible` for the other four. A stage that is not
a writer has no ``write`` method available to call (SEC-4.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from ..agents import Agent
from ..config import Config
from ..domain.models import Outline, Usage
from ..engines.base import Completion, Engine, Request
from ..security.sandbox import Workspace
from ..spec.flow import Stage as StageSpec

__all__ = ["Stage", "StageContext", "StageResult"]


@dataclass
class StageResult:
    """What a stage produced."""

    artefacts: tuple[str, ...] = field(default_factory=tuple)
    usage: Usage | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class StageContext:
    """Everything a stage may use. Nothing is imported; everything is passed."""

    spec: StageSpec
    agent: Agent
    config: Config
    workspace: Workspace
    bible: Any            # FileBible for writers, ReadOnlyBible for everyone else
    engine: Engine
    premise: str
    report: Callable[[str], None]
    call: Callable[..., Completion]
    log: Callable[[Mapping[str, Any]], None]
    outline: Outline | None = None
    state: Any = None

    # -- convenience over the config -------------------------------------

    def band(self, path: str) -> Any:
        return self.config.get(path)

    def chapter_bands(self) -> dict[str, Any]:
        """The numbers the Length Critic measures against, in one shape."""
        return {
            "words_min": self.config.get("novel.words_per_chapter.min"),
            "words_max": self.config.get("novel.words_per_chapter.max"),
            "words_target": self.config.get("novel.words_per_chapter.target"),
            "paragraphs_min": self.config.get("novel.paragraphs_per_chapter.min"),
            "paragraphs_max": self.config.get("novel.paragraphs_per_chapter.max"),
            "lines_min": self.config.get("novel.lines_per_chapter.min"),
            "lines_max": self.config.get("novel.lines_per_chapter.max"),
            "chars_per_line_max": self.config.get("novel.chars_per_line.max"),
        }


class Stage(Protocol):
    """One step of the pipeline."""

    def run(self, context: StageContext) -> StageResult:
        ...
