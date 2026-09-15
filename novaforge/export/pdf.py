"""``dist/book.pdf``, written from scratch.

No dependency. A PDF is a handful of objects, a cross-reference table and a
trailer, and the alternative - pulling in a rendering library for a
single-column book of Helvetica - costs more than it saves.

Two things here are worth knowing before changing anything:

**Line breaking is measured, not estimated.** Lines are broken against the real
Helvetica widths in :mod:`novaforge.export.metrics`, so the right margin is
where the config says it is. The Markdown exporter wraps by *character* count
because a terminal is monospaced; this one wraps by *width* because a page is
not. The same chapter therefore has a different line count in the two files,
which is correct.

**Model-written text is escaped (SEC-5.2).** An unescaped ``)`` inside a PDF
literal string does not corrupt one line - it ends the string early and
corrupts every object after it, and the file simply fails to open. Everything
outside printable ASCII is octal-encoded in WinAnsi.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ..textops import chapter_body, heading, paragraphs
from .base import ExportResult
from .metrics import string_width

__all__ = ["PAGE_SIZES", "PdfExporter", "pdf_string"]

MM_TO_PT = 72.0 / 25.4

# Width and height in points.
PAGE_SIZES = {
    "a4": (595.276, 841.890),
    "a5": (419.528, 595.276),
    "letter": (612.0, 792.0),
}

BODY_FONT = "Helvetica"
HEAD_FONT = "Helvetica-Bold"


def pdf_string(text: str) -> bytes:
    """Escape ``text`` for a PDF literal string (SEC-5.2).

    ``\\``, ``(`` and ``)`` are escaped; everything outside printable ASCII is
    octal-encoded from its WinAnsi byte. A character with no WinAnsi code
    becomes a bullet rather than being dropped, so a missing glyph is visible
    on the page instead of silently changing the prose.
    """
    out = bytearray(b"(")
    for char in text:
        try:
            code = char.encode("cp1252")[0]
        except (UnicodeEncodeError, IndexError):
            code = 0xB7  # middle dot
        if code in (0x5C, 0x28, 0x29):  # \ ( )
            out += b"\\" + bytes([code])
        elif 32 <= code <= 126:
            out.append(code)
        else:
            out += f"\\{code:03o}".encode("ascii")
    out += b")"
    return bytes(out)


@dataclass
class _Line:
    """One laid-out line: what to draw, in what font, at what size."""

    text: str
    font: str = BODY_FONT
    size: float = 10.5
    space_before: float = 0.0
    keep_with_next: bool = False


@dataclass
class _Page:
    lines: list[tuple[float, _Line]] = field(default_factory=list)
    number: int = 1


class PdfExporter:
    """Lays a manuscript out and writes it."""

    name = "pdf"

    def export(self, *, workspace, config, chapters: Sequence[str],
               synopsis: str = "") -> ExportResult:
        layout = _Layout(config)
        pages = layout.paginate(chapters, synopsis)
        data = _write_pdf(pages, layout)
        filename = str(config.get("outputs.pdf.filename"))
        workspace.write_bytes(f"dist/{filename}", data=data)
        size_name = str(config.get("outputs.pdf.page_size")).lower()
        return ExportResult(
            path=f"dist/{filename}",
            detail=(f"{len(pages)} pages, {size_name.upper()}, "
                    f"{layout.size:g}pt Helvetica, {len(data):,} bytes"),
        )


class _Layout:
    """Page geometry and the rules for filling it, all from the config."""

    def __init__(self, config) -> None:
        self.config = config
        size_name = str(config.get("outputs.pdf.page_size")).lower()
        if size_name not in PAGE_SIZES:
            raise ValueError(
                f"unknown page_size {size_name!r}; have {sorted(PAGE_SIZES)}"
            )
        self.width, self.height = PAGE_SIZES[size_name]
        margins = config.get("outputs.pdf.margins_mm")
        self.top = float(margins["top"]) * MM_TO_PT
        self.bottom = float(margins["bottom"]) * MM_TO_PT
        self.inner = float(margins["inner"]) * MM_TO_PT
        self.outer = float(margins["outer"]) * MM_TO_PT
        self.size = float(config.get("outputs.pdf.font_size_pt"))
        self.leading = self.size * float(config.get("outputs.pdf.line_height"))
        self.page_numbers = bool(config.get("outputs.pdf.page_numbers"))
        self.new_page_per_chapter = bool(config.get("outputs.pdf.chapter_on_new_page"))
        self.include_synopsis = bool(config.get("outputs.pdf.include_synopsis"))
        self.shrink_to_fit = bool(config.get("outputs.pdf.shrink_to_fit"))
        self.title = str(config.get("novel.title", "")) or "Untitled"
        self.author = str(config.get("novel.author"))

    @property
    def text_width(self) -> float:
        return self.width - self.inner - self.outer

    @property
    def text_height(self) -> float:
        return self.height - self.top - self.bottom

    def left_margin(self, page_number: int) -> float:
        """Recto pages bind on the left, verso on the right.

        Facing-page margins are the difference between a book and a stack of
        printouts: without this the gutter eats the inner text on half the
        pages.
        """
        return self.inner if page_number % 2 == 1 else self.outer

    # -- line breaking ---------------------------------------------------

    def wrap(self, text: str, font: str, size: float) -> list[str]:
        """Greedy wrap by measured width."""
        limit = self.text_width
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = word if not current else f"{current} {word}"
            if string_width(candidate, font, size) <= limit or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def fit_size(self, text: str, font: str, size: float) -> float:
        """Shrink one line until it fits, if ``shrink_to_fit`` is on.

        Only ever applies to a single unbreakable word wider than the column -
        a URL, say. Everything else is handled by wrapping, so this does not
        quietly rescale the book.
        """
        if not self.shrink_to_fit:
            return size
        width = string_width(text, font, size)
        if width <= self.text_width or width == 0:
            return size
        return max(4.0, size * self.text_width / width)

    # -- pagination ------------------------------------------------------

    def paginate(self, chapters: Sequence[str], synopsis: str) -> list[_Page]:
        pages: list[_Page] = []
        page = _Page(number=1)
        cursor = self.height - self.top

        def flush() -> None:
            nonlocal page, cursor
            pages.append(page)
            page = _Page(number=len(pages) + 1)
            cursor = self.height - self.top

        def place(line: _Line) -> None:
            nonlocal cursor
            needed = self.leading + line.space_before
            # A heading alone at the foot of a page is an orphan; keep it with
            # the first line of what it introduces.
            lookahead = self.leading if line.keep_with_next else 0.0
            if cursor - needed - lookahead < self.bottom:
                flush()
            cursor -= line.space_before
            cursor -= self.leading
            page.lines.append((cursor, line))

        # Title page.
        place(_Line(self.title, HEAD_FONT, self.size * 2.0,
                    space_before=self.text_height * 0.28))
        place(_Line(f"by {self.author}", BODY_FONT, self.size * 1.1,
                    space_before=self.leading))
        flush()

        if self.include_synopsis and synopsis.strip():
            place(_Line("Synopsis", HEAD_FONT, self.size * 1.4, keep_with_next=True))
            for text in self.wrap(" ".join(synopsis.split()), BODY_FONT, self.size):
                place(_Line(text, BODY_FONT, self.size))
            flush()

        for index, chapter in enumerate(chapters, start=1):
            if self.new_page_per_chapter and page.lines:
                flush()
            title = heading(chapter) or f"Chapter {index}"
            head_size = self.fit_size(title, HEAD_FONT, self.size * 1.5)
            for text in self.wrap(title, HEAD_FONT, head_size):
                place(_Line(text, HEAD_FONT, head_size,
                            space_before=self.leading, keep_with_next=True))
            for block in paragraphs(chapter_body(chapter)):
                flat = " ".join(block.split())
                for position, text in enumerate(self.wrap(flat, BODY_FONT, self.size)):
                    place(_Line(text, BODY_FONT,
                                self.fit_size(text, BODY_FONT, self.size),
                                space_before=self.leading * 0.4 if position == 0 else 0.0))

        if page.lines:
            pages.append(page)
        return pages


def _content_stream(page: _Page, layout: _Layout) -> bytes:
    """The drawing commands for one page."""
    left = layout.left_margin(page.number)
    parts: list[bytes] = []
    for y, line in page.lines:
        if not line.text:
            continue
        font_key = b"/F2" if line.font == HEAD_FONT else b"/F1"
        parts.append(
            b"BT " + font_key + f" {line.size:.3f} Tf 1 0 0 1 {left:.3f} {y:.3f} Tm ".encode()
            + pdf_string(line.text) + b" Tj ET\n"
        )

    if layout.page_numbers and page.number > 1:
        label = str(page.number)
        size = layout.size * 0.85
        x = left + (layout.text_width - string_width(label, BODY_FONT, size)) / 2
        y = layout.bottom * 0.55
        parts.append(
            b"BT /F1 " + f"{size:.3f} Tf 1 0 0 1 {x:.3f} {y:.3f} Tm ".encode()
            + pdf_string(label) + b" Tj ET\n"
        )
    return b"".join(parts)


def _write_pdf(pages: Sequence[_Page], layout: _Layout) -> bytes:
    """Assemble the objects, the cross-reference table and the trailer."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)  # object numbers are 1-based

    font_regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                       b"/Encoding /WinAnsiEncoding >>")
    font_bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                    b"/Encoding /WinAnsiEncoding >>")
    pages_id = add(b"")  # reserved; filled in once the kids are known

    kids: list[int] = []
    for page in pages:
        stream = zlib.compress(_content_stream(page, layout))
        contents_id = add(
            b"<< /Length " + str(len(stream)).encode() + b" /Filter /FlateDecode >>\n"
            b"stream\n" + stream + b"\nendstream"
        )
        page_id = add(
            b"<< /Type /Page /Parent " + str(pages_id).encode() + b" 0 R "
            b"/MediaBox [0 0 " + f"{layout.width:.3f} {layout.height:.3f}".encode() + b"] "
            b"/Resources << /Font << /F1 " + str(font_regular).encode() + b" 0 R "
            b"/F2 " + str(font_bold).encode() + b" 0 R >> >> "
            b"/Contents " + str(contents_id).encode() + b" 0 R >>"
        )
        kids.append(page_id)

    objects[pages_id - 1] = (
        b"<< /Type /Pages /Count " + str(len(kids)).encode() + b" /Kids ["
        + b" ".join(f"{k} 0 R".encode() for k in kids) + b"] >>"
    )
    catalog_id = add(b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>")
    info_id = add(
        b"<< /Title " + pdf_string(layout.title)
        + b" /Author " + pdf_string(layout.author)
        + b" /Producer " + pdf_string("NovaForge") + b" >>"
    )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj\n" + body + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (b"trailer\n<< /Size " + str(len(objects) + 1).encode()
            + b" /Root " + str(catalog_id).encode() + b" 0 R"
            + b" /Info " + str(info_id).encode() + b" 0 R >>\n"
            b"startxref\n" + str(xref_at).encode() + b"\n%%EOF\n")
    return bytes(out)
