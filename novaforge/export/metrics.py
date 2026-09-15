"""Helvetica and Helvetica-Bold character widths, in units of 1/1000 em.

Straight from the Adobe AFM files for two of the base-14 fonts, which every
conforming PDF reader already has - so nothing is embedded and a 90KB
manuscript stays 90KB.

These numbers do exactly one job: deciding where a line breaks. Get an entry
wrong and a single line breaks one word early. Nothing else shifts, nothing
raises, and the only way to notice is to look - which is why this table is
separated from the writer and tested against known strings.
"""

from __future__ import annotations

__all__ = ["DEFAULT_WIDTH", "string_width", "widths_for"]

DEFAULT_WIDTH = 556  # an unmapped character is rendered as a bullet this wide

# ASCII 32-126, in order.
_HELVETICA = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
)

_HELVETICA_BOLD = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
)

# The WinAnsi (cp1252) codes above ASCII that prose actually reaches: curly
# quotes and dashes. A manuscript is full of them, and treating an em dash as
# the default width would mis-break every line that contains one.
_EXTRA = {
    "helvetica": {0x91: 222, 0x92: 222, 0x93: 333, 0x94: 333,
                  0x96: 556, 0x97: 1000, 0xA0: 278, 0x85: 1000},
    "helvetica-bold": {0x91: 238, 0x92: 238, 0x93: 500, 0x94: 500,
                       0x96: 556, 0x97: 1000, 0xA0: 278, 0x85: 1000},
}


def widths_for(font: str) -> dict[int, int]:
    """Byte value -> width, for one font, in WinAnsi encoding."""
    table = _HELVETICA_BOLD if "bold" in font.lower() else _HELVETICA
    widths = {code: table[code - 32] for code in range(32, 127)}
    widths.update(_EXTRA["helvetica-bold" if "bold" in font.lower() else "helvetica"])
    return widths


def string_width(text: str, font: str, size: float) -> float:
    """Width of ``text`` in points at ``size``.

    Characters with no WinAnsi code are measured at :data:`DEFAULT_WIDTH`,
    matching what the writer substitutes for them, so the measurement and the
    rendering never disagree.
    """
    widths = widths_for(font)
    total = 0
    for char in text:
        try:
            code = char.encode("cp1252")[0]
        except (UnicodeEncodeError, IndexError):
            total += DEFAULT_WIDTH
            continue
        total += widths.get(code, DEFAULT_WIDTH)
    return total * size / 1000.0
