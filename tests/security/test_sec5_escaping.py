"""SEC-5 - output sanitisation.

Each of these failures is invisible on disk, which is why they are tested by
what they *prevent* rather than by what they produce. An unescaped ``)`` does
not corrupt one line of a PDF; it ends the literal string early and every byte
offset in the cross-reference table after it becomes wrong.

`xml_escape` and `svg_text` are not on the shipping path — CHG-001 removed the
EPUB and the SVG cover — and they are tested anyway, because an untested
escaper is worse than none. There is a test asserting they really are unused,
so "off the shipping path" stays a fact rather than a stale comment.
"""

from __future__ import annotations

import pytest

from novaforge.security.escaping import (
    markdown_prose,
    pdf_string,
    safe_zip_name,
    strip_control,
    svg_text,
    xml_escape,
)


class TestStripControl:
    @pytest.mark.parametrize("char", ["​", "‮", "­", "⁠", chr(0)])
    def test_invisible_characters_are_removed(self, char):
        assert strip_control(f"a{char}b") == "ab"

    def test_layout_whitespace_survives(self):
        assert strip_control("a\nb\tc") == "a\nb\tc"

    def test_ordinary_text_is_untouched(self):
        text = "Mara Kassab — «el eco» — checked the hatch."
        assert strip_control(text) == text

    def test_empty_and_none_are_tolerated(self):
        assert strip_control("") == ""
        assert strip_control(None) == ""


class TestMarkdownProse:
    @pytest.mark.parametrize("line,escaped", [
        ("## The Cold Lamp", "\\## The Cold Lamp"),
        ("> quoted", "\\> quoted"),
        ("- a bullet", "\\- a bullet"),
        ("1. numbered", "\\1. numbered"),
        ("| a table", "\\| a table"),
    ])
    def test_structure_at_the_start_of_a_line_is_neutralised(self, line, escaped):
        """SEC-5.1. Otherwise a paragraph beginning '## ' silently becomes a
        chapter heading and the table of contents is wrong in a way nobody
        notices until print."""
        assert markdown_prose(line) == escaped

    def test_indentation_is_preserved(self):
        assert markdown_prose("  - a bullet") == "  \\- a bullet"

    @pytest.mark.parametrize("line", [
        "a # mid-sentence hash",
        "the value was 1.5 exactly",
        "Mara said no.",
        "",
    ])
    def test_prose_is_left_alone(self, line):
        """A '#' mid-sentence is a '#'. Escaping it would corrupt the prose to
        prevent a problem that does not exist."""
        assert markdown_prose(line) == line

    def test_the_text_stays_readable(self):
        """Escaped, not dropped: the line still says what the author wrote."""
        assert "The Cold Lamp" in markdown_prose("## The Cold Lamp")


class TestPdfString:
    @pytest.mark.parametrize("raw,expected", [
        ("plain", b"(plain)"),
        ("a(b", b"(a\\(b)"),
        ("a)b", b"(a\\)b)"),
        ("a\\b", b"(a\\\\b)"),
        ("", b"()"),
    ])
    def test_structural_characters_are_escaped(self, raw, expected):
        assert pdf_string(raw) == expected

    def test_an_unbalanced_paren_cannot_end_the_string_early(self):
        """The failure this prevents: every object after it is misaddressed and
        the document will not open."""
        out = pdf_string("she said (quietly) — or did she?)")
        assert out.count(b"(") - out.count(b"\\(") == 1
        assert out.count(b")") - out.count(b"\\)") == 1

    @pytest.mark.parametrize("char,octal", [("—", b"\\227"), ("“", b"\\223")])
    def test_non_ascii_is_octal_encoded_from_its_winansi_byte(self, char, octal):
        assert octal in pdf_string(char)

    def test_an_unmappable_glyph_becomes_a_visible_bullet(self):
        """A silently dropped character changes the prose; a bullet is seen."""
        assert pdf_string("中") == b"(\\267)"

    def test_control_characters_never_reach_the_page_raw(self):
        assert b"\n" not in pdf_string("a\nb")

    def test_the_result_is_always_a_balanced_literal(self):
        for text in ("", "()", "\\\\", "a" * 500, "— “quoted” —"):
            out = pdf_string(text)
            assert out.startswith(b"(") and out.endswith(b")")


class TestSafeZipName:
    @pytest.mark.parametrize("name", ["book.md", "OEBPS/ch01.xhtml", "a_b-c.1"])
    def test_acceptable_names_pass_through(self, name):
        assert safe_zip_name(name) == name

    @pytest.mark.parametrize("name", [
        "../escape.md", "..\\escape.md", "/absolute", "a/../b",
        "-leading", ".hidden", "with space.md", "a|b", "", "x" * 200,
    ])
    def test_unsafe_names_are_refused_on_write(self, name):
        """SEC-5.4. Building an archive with a '../' entry is how a zip-slip
        payload is *created*, not only how it is exploited."""
        with pytest.raises(ValueError):
            safe_zip_name(name)

    def test_it_is_a_whitelist_not_a_blacklist(self):
        with pytest.raises(ValueError, match="alphanumeric"):
            safe_zip_name("café.md")


class TestOffTheShippingPath:
    def test_xml_escape_handles_the_five_entities(self):
        assert xml_escape("<a>&</a>") == "&lt;a&gt;&amp;&lt;/a&gt;"
        assert xml_escape("'\"", attribute=True) == "&apos;&quot;"

    def test_ampersand_is_escaped_first(self):
        """Otherwise the ampersands the other replacements introduce get
        escaped a second time and '<' renders as '&amp;lt;'."""
        assert xml_escape("<") == "&lt;"
        assert xml_escape("&lt;") == "&amp;lt;"

    def test_xml_escape_also_strips_invisibles(self):
        assert xml_escape("a​b") == "ab"

    def test_svg_text_collapses_whitespace(self):
        """SVG collapses runs of space when rendering, so a caller who wanted
        them would get a different image than the string implies."""
        assert svg_text("  a   b  ") == "a b"

    def test_svg_text_escapes_as_xml(self):
        assert svg_text("<title> & co") == "&lt;title&gt; &amp; co"

    def test_they_really_are_unused(self):
        """Stated in the docstrings; checked here so it stays true. If an XML
        format returns, this test is what tells you to update the claim."""
        import pathlib

        from novaforge.config import package_root

        callers = []
        for path in (package_root() / "novaforge").rglob("*.py"):
            if path.name == "escaping.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "xml_escape(" in text or "svg_text(" in text:
                callers.append(path.name)
        assert callers == [], callers  # re-exported by name, called by nothing


class TestOnTheShippingPath:
    def test_every_text_artefact_is_stripped_on_write(self, workspace):
        """SEC-5.3 says 'every artefact string'. Workspace.write_text is the
        single place they all pass through, which is the only way that can be a
        fact rather than a habit each caller has to remember."""
        workspace.write_text("a.md", content="hola​mundo‮")
        assert workspace.read_text("a.md") == "holamundo"

    def test_a_non_string_is_refused_before_the_file_is_touched(self, workspace):
        """strip_control treats None as '', which would turn a caller's bug
        into a silently truncated artefact."""
        workspace.write_text("a.md", content="original")
        with pytest.raises(TypeError):
            workspace.write_text("a.md", content=None)  # type: ignore[arg-type]
        assert workspace.read_text("a.md") == "original"

    def test_the_exporters_use_the_shared_module(self):
        """Not their own copies. Two escapers that drift apart are worse than
        one that is wrong, because only one of them gets fixed."""
        from novaforge.export import markdown, pdf

        assert markdown.markdown_prose.__module__ == "novaforge.security.escaping"
        assert pdf.pdf_string.__module__ == "novaforge.security.escaping"
