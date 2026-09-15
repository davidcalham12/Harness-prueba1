"""Turning approved chapters into artefacts.

Which formats are written is ``outputs.formats`` in the config, not a decision
in code. A format the config asks for and this build cannot produce is reported
by name: a run that quietly writes one file when two were asked for is a run
that lies in its summary.

The two exporters wrap differently on purpose. Markdown wraps by *character*
count, because a terminal and a diff are monospaced; the PDF wraps by *measured
width*, because a page is not. The same chapter therefore has a different line
count in each, and that is correct rather than a bug.
"""

from __future__ import annotations

from .base import ExportResult, Exporter
from .markdown import MarkdownExporter
from .pdf import PdfExporter

__all__ = ["EXPORTERS", "ExportResult", "Exporter", "MarkdownExporter",
           "PdfExporter", "UnknownFormat", "build_exporters"]


class UnknownFormat(KeyError):
    """``outputs.formats`` names a format with no exporter."""


EXPORTERS = {"markdown": MarkdownExporter, "pdf": PdfExporter}


def build_exporters(formats):
    exporters = []
    missing = []
    for name in formats:
        key = str(name).strip().lower()
        if key in EXPORTERS:
            exporters.append(EXPORTERS[key]())
        else:
            missing.append(key)
    return tuple(exporters), tuple(missing)
