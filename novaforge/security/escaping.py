"""SEC-5 - output sanitisation.

Model-written text is embedded in formats that have structural syntax of their
own, and **each of these failures is invisible on disk**. That is what makes
them worth a module rather than a line at each call site:

* An unescaped ``)`` inside a PDF literal string does not corrupt one line. It
  ends the string early, every byte offset in the cross-reference table after
  it becomes wrong, and the document will not open at all.
* A paragraph that happens to begin ``## `` silently becomes a chapter heading
  in the Markdown manuscript, and the table of contents is then wrong in a way
  nobody notices until print.
* A zip entry named ``../x`` is how a zip-slip payload is *created*, not only
  how it is exploited. The whitelist is on write.

:func:`xml_escape` and :func:`svg_text` are **not on the shipping path**. CHG-001
removed the EPUB and the SVG cover, and nothing in this build calls them. They
are kept, and tested, because an untested escaper is worse than none and these
are the correct tool the moment an XML format returns. Their absence from the
pipeline is stated here rather than discovered later.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "markdown_prose",
    "pdf_string",
    "safe_zip_name",
    "strip_control",
    "svg_text",
    "xml_escape",
]

# Markdown structure, but only where it is structural: at the start of a line.
# A `#` mid-sentence is a `#`, and escaping it would corrupt the prose to
# prevent a problem that does not exist.
_MARKDOWN_STRUCTURE = re.compile(r"^(\s*)(#{1,6}\s|>\s|[-*+]\s|\d+\.\s|\|)")

_ZIP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_XML_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"),
                ('"', "&quot;"), ("'", "&apos;"))


def strip_control(text: str) -> str:
    """Remove Unicode ``Cc``/``Cf`` from a string bound for an artefact.

    Tabs and newlines survive because they are layout. Everything else in those
    categories is invisible to a reader and meaningful to a parser, which is
    the worst combination a character can have in a file somebody will diff.
    """
    return "".join(
        ch for ch in (text or "")
        if ch in "\t\n" or unicodedata.category(ch) not in ("Cc", "Cf")
    )


def markdown_prose(line: str) -> str:
    """Neutralise Markdown structure at the start of a prose line (SEC-5.1).

    Escapes the marker rather than dropping it, so the line still reads as the
    author wrote it — ``## The Cold Lamp`` stays visible as text instead of
    silently becoming a heading or silently losing its hashes.
    """
    match = _MARKDOWN_STRUCTURE.match(line or "")
    if not match:
        return line
    indent, token = match.group(1), match.group(2)
    return f"{indent}\\{token.lstrip()}{line[match.end():]}"


def pdf_string(text: str) -> bytes:
    """Escape ``text`` for a PDF literal string (SEC-5.2).

    ``\\``, ``(`` and ``)`` are escaped; everything outside printable ASCII is
    octal-encoded from its WinAnsi byte. A character with no WinAnsi code
    becomes a middle dot rather than being dropped, so a missing glyph is
    visible on the page instead of quietly changing the prose.
    """
    out = bytearray(b"(")
    for char in text or "":
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


def safe_zip_name(name: str) -> str:
    """Return ``name`` if it is safe as a zip entry, else raise (SEC-5.4).

    A whitelist, not a blacklist, and enforced when the archive is *written*.
    Building an archive with a ``../`` entry is how a zip-slip payload is
    created; refusing to write one means this program cannot be the source of
    that attack even if something downstream is careless.
    """
    candidate = str(name or "")
    for part in candidate.replace("\\", "/").split("/"):
        if not _ZIP_NAME.match(part):
            raise ValueError(
                f"unsafe zip entry name {name!r}: the component {part!r} is not "
                f"alphanumeric-plus-dot-dash-underscore, starting with an "
                f"alphanumeric (SEC-5.4)"
            )
    return candidate


# -- not on the shipping path -------------------------------------------------


def xml_escape(text: str, *, attribute: bool = False) -> str:
    """Escape ``text`` for XML character data, or for an attribute value.

    **Not on the shipping path.** Nothing in this build writes XML; CHG-001
    removed the EPUB. Kept and tested because an untested escaper is worse than
    none, and this is the correct tool the moment an XML format returns.

    ``&`` is replaced first, or the ampersands introduced by the later
    replacements would be escaped a second time and ``<`` would render as
    ``&amp;lt;``.
    """
    out = strip_control(text)
    for char, entity in _XML_ESCAPES if attribute else _XML_ESCAPES[:3]:
        out = out.replace(char, entity)
    return out


def svg_text(text: str) -> str:
    """Escape ``text`` for an SVG ``<text>`` element.

    **Not on the shipping path.** CHG-001 removed the SVG cover.

    SVG is XML, so this is :func:`xml_escape` plus one thing XML does not care
    about: a run of spaces collapses when rendered, so a caller who wanted them
    would get a different image than the string implies. Collapsing here makes
    the string and the render agree.
    """
    return re.sub(r"\s+", " ", xml_escape(text)).strip()
