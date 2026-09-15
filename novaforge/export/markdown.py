"""The Markdown manuscript.

Wrapped at ``novel.chars_per_line.max``, because a manuscript is read in a
terminal and a diff as often as in a viewer, and an unwrapped paragraph makes
both useless. The same width the Length Critic counted lines at, so "44 lines"
in the run report is the number of lines in the file.

Model-written prose is embedded in a format with structural syntax of its own,
so a paragraph that happens to begin ``## `` would silently become a chapter
heading and the table of contents would then be wrong in a way nobody notices
until print. :func:`markdown_prose` neutralises structure at the start of a
prose line. That is SEC-5's job; this module carries the minimum of it that the
shipping path needs.
"""

from __future__ import annotations

import re

from ..textops import chapter_body, count_words, heading, paragraphs, wrap_paragraph
from .base import ExportResult

__all__ = ["MarkdownExporter", "markdown_prose"]

_STRUCTURAL = re.compile(r"^(\s*)(#{1,6}\s|>\s|[-*+]\s|\d+\.\s|\|)")


def markdown_prose(line: str) -> str:
    """Neutralise Markdown structure at the start of a prose line (SEC-5.1)."""
    match = _STRUCTURAL.match(line)
    if not match:
        return line
    indent, token = match.group(1), match.group(2)
    return f"{indent}\\{token.lstrip()}{line[match.end():]}"


class MarkdownExporter:
    """``dist/book.md`` - one file, wrapped, with a table of contents."""

    name = "markdown"
    filename_key = "outputs.markdown.filename"

    def export(self, *, workspace, config, chapters, synopsis: str = "") -> ExportResult:
        width = int(config.get("novel.chars_per_line.max"))
        filename = str(config.get("outputs.markdown.filename"))
        title = str(config.get("novel.title", "")) or "Untitled"
        author = str(config.get("novel.author"))
        include_synopsis = bool(config.get("outputs.markdown.include_synopsis"))

        lines: list[str] = [f"# {title}", "", f"*by {author}*", ""]

        if include_synopsis and synopsis.strip():
            lines += ["## Synopsis", ""]
            lines += self._wrap(synopsis, width)
            lines += [""]

        titles = [heading(text) or f"Chapter {i}" for i, text in enumerate(chapters, 1)]
        lines += ["## Contents", ""]
        for index, chapter_title in enumerate(titles, start=1):
            lines.append(f"{index}. {chapter_title}")
        lines += [""]

        total_words = 0
        for index, text in enumerate(chapters, start=1):
            lines += [f"## {titles[index - 1]}", ""]
            body = chapter_body(text)
            total_words += count_words(body)
            lines += self._wrap(body, width)
            lines += [""]

        lines += ["---", "",
                  f"*{len(chapters)} chapters, {total_words:,} words, "
                  f"wrapped at {width} columns.*"]

        workspace.write_text(f"dist/{filename}", content="\n".join(lines).rstrip() + "\n")
        return ExportResult(
            path=f"dist/{filename}",
            detail=(f"{len(chapters)} chapters, {total_words:,} words, "
                    f"wrapped at {width} columns"),
        )

    @staticmethod
    def _wrap(text: str, width: int) -> list[str]:
        out: list[str] = []
        for block in paragraphs(text):
            flat = " ".join(block.split())
            wrapped = wrap_paragraph(flat, width)
            out.extend(markdown_prose(line) for line in wrapped)
            out.append("")
        while out and not out[-1]:
            out.pop()
        return out
