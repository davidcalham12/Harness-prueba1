"""The stage registry - the map from a spec's ``impl`` to code.

``specs/flow.yaml`` says *what* each stage is and in what order; this package
says *how* each kind of stage runs. The orchestrator only ever looks a stage up
here by its ``impl`` string, which is why reordering the YAML changes the run
and changes no Python.

Adding a new agent that has an existing shape (another Bible section, another
critic-gated loop) needs no entry here at all - it is a new stage in the YAML
pointing at an ``impl`` that already exists. An entry is only needed for a
genuinely new *kind* of step.
"""

from __future__ import annotations

from typing import Mapping

from .base import Stage, StageContext, StageResult
from .bible_sections import BibleMultiSectionStage, BibleSectionStage
from .chapters import ChapterLoopStage
from .outline import OutlineStage
from .publish import PublishStage
from .style import StylePassStage

__all__ = [
    "IMPLEMENTATIONS",
    "Stage",
    "StageContext",
    "StageResult",
    "UnknownImplementation",
    "build_stage",
]


class UnknownImplementation(KeyError):
    """The spec names an ``impl`` with no registered class."""


IMPLEMENTATIONS: Mapping[str, type] = {
    "bible_section": BibleSectionStage,
    "bible_multi_section": BibleMultiSectionStage,
    "outline": OutlineStage,
    "chapter_loop": ChapterLoopStage,
    "style_pass": StylePassStage,
    "publish": PublishStage,
}


def build_stage(impl: str):
    key = (impl or "").strip()
    if key not in IMPLEMENTATIONS:
        raise UnknownImplementation(
            f"specs/flow.yaml names impl {key!r}, which has no implementation; "
            f"registered: {sorted(IMPLEMENTATIONS)}"
        )
    return IMPLEMENTATIONS[key]()
