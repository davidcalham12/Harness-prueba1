"""Value objects passed between stages.

Nothing here does IO or calls a model. The orchestrator, the critics and the
exporters all speak in these types, which is what lets a stage be tested with a
literal instead of a run directory.
"""

from __future__ import annotations

from .models import (
    ChapterPlan,
    ChapterRecord,
    Critique,
    Finding,
    GateDecision,
    Outline,
    Usage,
)

__all__ = [
    "ChapterPlan",
    "ChapterRecord",
    "Critique",
    "Finding",
    "GateDecision",
    "Outline",
    "Usage",
]
