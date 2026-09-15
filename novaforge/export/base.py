"""What an exporter returns.

Each exporter describes itself, because the interesting number differs:
Markdown is wrapped at a character count, the PDF is paginated at a measured
width. One shared summary line would be wrong for one of them, and a run report
that says "wrapped at 64" about a PDF is a run report that is lying.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

__all__ = ["ExportResult", "Exporter"]


@dataclass(frozen=True)
class ExportResult:
    """Where the artefact landed, and what it actually says."""

    path: str
    detail: str = ""


@runtime_checkable
class Exporter(Protocol):
    """Turns approved chapters into one artefact."""

    name: str

    def export(self, *, workspace, config, chapters: Sequence[str],
               synopsis: str = "") -> ExportResult:
        ...
