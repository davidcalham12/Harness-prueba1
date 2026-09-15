"""The PDF exporter, and SEC-5's share of it.

A PDF fails differently from a text file. An unescaped ``)`` does not corrupt
one line - it ends a literal string early, every byte offset in the
cross-reference table after it becomes wrong, and the document will not open at
all. So the escaping tests are not stylistic; they are the difference between a
file and rubble.

There is no PDF reader in this environment, so validity is asserted
structurally: the header, the xref offsets pointing at their objects, the page
tree, and every content stream decompressing. That is weaker than opening it in
Acrobat and stronger than checking the file is non-empty.
"""

from __future__ import annotations

import re
import zlib

import pytest

from conftest import run_novel
from novaforge.config import load_config
from novaforge.export.metrics import DEFAULT_WIDTH, string_width, widths_for
from novaforge.export.pdf import PAGE_SIZES, PdfExporter, pdf_string

CHAPTERS = [
    "# Chapter 1 — Contact by Law\n\n" + "Mara Kassab checked the hatch. " * 40,
    "# Chapter 2 — The Cold Lamp\n\n" + "Ilo Vega counted the seams. " * 40,
]


@pytest.fixture
def book(tmp_path, workspace):
    config = load_config(profile="tiny")
    result = PdfExporter().export(workspace=workspace, config=config,
                                  chapters=CHAPTERS, synopsis="A synopsis.")
    return workspace.read_bytes(result.path), result


class TestMetrics:
    def test_known_helvetica_widths(self):
        """Straight from the AFM. A wrong entry breaks one line one word early
        and raises nothing, so the table is pinned."""
        widths = widths_for("Helvetica")
        assert widths[ord(" ")] == 278
        assert widths[ord("M")] == 833
        assert widths[ord("i")] == 222
        assert widths[ord("W")] == 944

    def test_bold_is_a_different_table(self):
        """Not uniformly wider: 'M' and 'a' are identical in both, 'b' is not.
        Picking a character that happens to match would make this test pass
        against a table that was never loaded."""
        bold, regular = widths_for("Helvetica-Bold"), widths_for("Helvetica")
        assert bold[ord("b")] == 611 and regular[ord("b")] == 556
        assert bold[ord("l")] == 278 and regular[ord("l")] == 222
        assert bold[ord("M")] == regular[ord("M")] == 833

    def test_a_string_measures_as_the_sum_of_its_characters(self):
        assert string_width("MM", "Helvetica", 10) == pytest.approx(833 * 2 * 10 / 1000)

    def test_width_scales_with_size(self):
        assert string_width("hello", "Helvetica", 20) == \
            pytest.approx(string_width("hello", "Helvetica", 10) * 2)

    def test_prose_punctuation_is_measured_not_defaulted(self):
        """An em dash is 1000 units. Treating it as the default would mis-break
        every line that contains one, and the mock writes them constantly."""
        assert widths_for("Helvetica")[0x97] == 1000
        assert widths_for("Helvetica")[0x93] == 333

    def test_an_unmappable_character_falls_back_predictably(self):
        assert string_width("中", "Helvetica", 10) == \
            pytest.approx(DEFAULT_WIDTH * 10 / 1000)

    def test_the_empty_string_is_zero_wide(self):
        assert string_width("", "Helvetica", 10) == 0


class TestEscaping:
    @pytest.mark.parametrize("raw,expected", [
        ("plain", b"(plain)"),
        ("a(b", b"(a\\(b)"),
        ("a)b", b"(a\\)b)"),
        ("a\\b", b"(a\\\\b)"),
    ])
    def test_structural_characters_are_escaped(self, raw, expected):
        assert pdf_string(raw) == expected

    def test_an_unbalanced_paren_cannot_end_the_string_early(self):
        """The failure this prevents: every object after it is misaddressed and
        the file does not open."""
        out = pdf_string("she said (quietly) — or did she?)")
        assert out.count(b"(") - out.count(b"\\(") == 1   # only the opener
        assert out.count(b")") - out.count(b"\\)") == 1   # only the closer

    def test_non_ascii_is_octal_encoded(self):
        assert b"\\227" in pdf_string("—")
        assert b"\\223" in pdf_string("“")

    def test_an_unmappable_glyph_becomes_a_visible_bullet_not_a_deletion(self):
        """A silently dropped character changes the prose; a bullet is seen."""
        assert pdf_string("中") == b"(\\267)"

    def test_control_characters_never_reach_the_page_raw(self):
        assert b"\n" not in pdf_string("a\nb")


class TestStructure:
    def test_it_starts_and_ends_correctly(self, book):
        data, _ = book
        assert data.startswith(b"%PDF-1.4")
        assert data.rstrip().endswith(b"%%EOF")

    def test_every_xref_offset_points_at_its_object(self, book):
        """The table is the one part of a PDF that is unforgiving: an offset
        one byte out and no reader will open the file."""
        data, _ = book
        start = int(re.search(rb"startxref\s+(\d+)", data).group(1))
        assert data[start:start + 4] == b"xref"
        entries = re.findall(rb"(\d{10}) (\d{5}) ([nf])", data[start:])
        for number, (offset, _gen, kind) in enumerate(entries):
            if kind == b"n":
                assert data[int(offset):].startswith(b"%d 0 obj" % number)

    def test_the_page_tree_is_consistent(self, book):
        data, _ = book
        objects = dict((int(n), b) for n, b in
                       re.findall(rb"(\d+) 0 obj\n(.*?)\nendobj", data, re.S))
        root = int(re.search(rb"/Root (\d+)", data).group(1))
        assert b"/Catalog" in objects[root]
        pages_id = int(re.search(rb"/Pages (\d+)", objects[root]).group(1))
        count = int(re.search(rb"/Count (\d+)", objects[pages_id]).group(1))
        kids = re.findall(rb"(\d+) 0 R",
                          re.search(rb"/Kids \[(.*?)\]", objects[pages_id], re.S).group(1))
        assert count == len(kids)
        assert all(b"/Type /Page" in objects[int(k)] for k in kids)

    def test_every_content_stream_decompresses(self, book):
        data, _ = book
        streams = re.findall(
            rb"<< /Length \d+ /Filter /FlateDecode >>\nstream\n(.*?)\nendstream", data, re.S)
        assert streams
        for stream in streams:
            assert zlib.decompress(stream)

    def test_nothing_is_embedded(self, book):
        """Base-14 fonts: a 90KB manuscript stays 90KB."""
        data, _ = book
        assert b"/FontFile" not in data
        assert b"/WinAnsiEncoding" in data


class TestLayout:
    def test_the_page_size_comes_from_the_config(self, workspace):
        for profile, expected in (("tiny", "a5"), ("small", "a4")):
            config = load_config(profile=profile)
            result = PdfExporter().export(workspace=workspace, config=config,
                                          chapters=CHAPTERS, synopsis="")
            data = workspace.read_bytes(result.path)
            width, height = PAGE_SIZES[expected]
            assert b"/MediaBox [0 0 %s" % f"{width:.3f}".encode() in data

    def test_an_unknown_page_size_is_refused(self, workspace):
        config = load_config(profile="tiny",
                             overrides={"outputs": {"pdf": {"page_size": "napkin"}}})
        with pytest.raises(ValueError, match="page_size"):
            PdfExporter().export(workspace=workspace, config=config,
                                 chapters=CHAPTERS, synopsis="")

    def test_no_line_is_wider_than_the_text_column(self, workspace):
        """The claim the metrics table exists to support."""
        from novaforge.export.pdf import _Layout

        config = load_config(profile="tiny")
        layout = _Layout(config)
        for chapter in CHAPTERS:
            for line in layout.wrap(" ".join(chapter.split()), "Helvetica", layout.size):
                assert string_width(line, "Helvetica", layout.size) <= layout.text_width

    def test_a_word_wider_than_the_column_still_gets_a_line(self, workspace):
        from novaforge.export.pdf import _Layout

        layout = _Layout(load_config(profile="tiny"))
        assert "x" * 400 in layout.wrap("x" * 400, "Helvetica", layout.size)

    def test_facing_pages_alternate_their_margin(self, workspace):
        from novaforge.export.pdf import _Layout

        layout = _Layout(load_config(profile="tiny"))
        assert layout.left_margin(1) == layout.inner
        assert layout.left_margin(2) == layout.outer

    def test_each_chapter_starts_a_new_page_when_configured(self, workspace):
        from novaforge.export.pdf import _Layout

        layout = _Layout(load_config(profile="tiny"))
        assert layout.new_page_per_chapter
        pages = layout.paginate(CHAPTERS, "")
        titles = [line.text for page in pages for _, line in page.lines
                  if line.text.startswith("Chapter ")]
        assert titles == ["Chapter 1 — Contact by Law", "Chapter 2 — The Cold Lamp"]

    def test_chapter_titles_open_their_own_page(self, workspace):
        from novaforge.export.pdf import _Layout

        layout = _Layout(load_config(profile="tiny"))
        for page in layout.paginate(CHAPTERS, ""):
            heads = [i for i, (_, line) in enumerate(page.lines)
                     if line.text.startswith("Chapter ")]
            assert heads in ([], [0])

    def test_no_line_is_placed_below_the_bottom_margin(self, workspace):
        from novaforge.export.pdf import _Layout

        layout = _Layout(load_config(profile="tiny"))
        for page in layout.paginate(CHAPTERS, "A synopsis."):
            for y, _line in page.lines:
                assert y >= layout.bottom - 0.01


class TestReporting:
    def test_the_result_describes_a_pdf_not_a_text_file(self, book):
        _, result = book
        assert result.path == "dist/book.pdf"
        assert "pages" in result.detail and "A5" in result.detail
        assert "columns" not in result.detail

    def test_it_is_written_in_a_full_run(self, tmp_path):
        _, _, space = run_novel(tmp_path, slug="pdf")
        assert space.exists("dist/book.pdf")
        assert space.read_bytes("dist/book.pdf").startswith(b"%PDF-")

    def test_the_two_exporters_disagree_about_line_count_on_purpose(self, tmp_path):
        """Markdown wraps by character count, the PDF by measured width."""
        _, _, space = run_novel(tmp_path, slug="both")
        md_lines = len(space.read_text("dist/book.md").splitlines())
        pdf = space.read_bytes("dist/book.pdf")
        streams = re.findall(
            rb"<< /Length \d+ /Filter /FlateDecode >>\nstream\n(.*?)\nendstream", pdf, re.S)
        pdf_lines = sum(zlib.decompress(s).count(b" Tj") for s in streams)
        assert md_lines != pdf_lines
