"""Text measurement and Bible parsing.

Parsing is forgiving because a *model* wrote the text being parsed. The tests
therefore pin both halves of that: the shapes that must be recognised, and the
junk that must be ignored without raising.
"""

from __future__ import annotations

from novaforge.textops import (
    chapter_body,
    count_lines,
    count_paragraphs,
    count_sentences,
    count_words,
    heading,
    parse_characters,
    parse_outline,
    parse_world_rules,
    slugify,
    wrap_paragraph,
    wrap_text,
)


class TestMeasurement:
    def test_counts(self):
        assert count_words("uno dos tres") == 3
        assert count_lines("a\n\n\nb") == 2
        assert count_paragraphs("a\n\nb\n\nc") == 3

    def test_sentence_count_includes_unterminated_trailing_fragment(self):
        assert count_sentences("One. Two. Three") == 3
        assert count_sentences("") == 0

    def test_empty_input_never_raises(self):
        for fn in (count_words, count_lines, count_paragraphs, count_sentences):
            assert fn("") == 0
            assert fn(None) == 0


class TestWrapping:
    def test_wrap_respects_the_width(self):
        wrapped = wrap_text("palabra " * 60, 64)
        assert max(len(line) for line in wrapped.splitlines()) <= 64

    def test_wrap_loses_no_words(self):
        assert count_words(wrap_text("palabra " * 60, 64)) == 60

    def test_a_word_longer_than_the_width_gets_its_own_line(self):
        """Breaking it would corrupt it; a long compound is still one word."""
        lines = wrap_paragraph("short " + "x" * 90, 20)
        assert "x" * 90 in lines

    def test_headings_pass_through_unwrapped(self):
        """A wrapped heading is a broken heading."""
        long_heading = "# " + "titulo " * 20
        assert long_heading.strip() in wrap_text(long_heading + "\n\ncuerpo", 20)


class TestBibleParsing:
    CAST = "- **Mara Kassab** — salvage pilot; steady, secretive\n- **Ilo Vega** — engineer\n"

    def test_reads_the_shape_the_architect_is_asked_for(self):
        cast = parse_characters(self.CAST)
        assert [c.name for c in cast] == ["Mara Kassab", "Ilo Vega"]
        assert cast[0].role == "salvage pilot"
        assert cast[0].traits == ("steady", "secretive")
        assert cast[0].surname == "Kassab"

    def test_ignores_lines_that_are_not_cast_entries(self):
        assert len(parse_characters(self.CAST + "prose about nothing\n## Heading\n")) == 2

    def test_duplicate_names_are_collapsed(self):
        assert len(parse_characters("- **A B** — x\n- **a b** — y\n")) == 1

    def test_malformed_input_returns_empty_rather_than_raising(self):
        assert parse_characters("") == ()
        assert parse_characters("no bullets here") == ()

    def test_rules_are_read_only_from_a_rules_heading(self):
        """The Science Auditor must not audit against a faction bullet."""
        markdown = (
            "# World\n- not a rule\n"
            "## Factions\n- **the Combine** — also not a rule\n"
            "## Rules\n- **No FTL**\n- Inertia is never cancelled\n"
            "## Texture\n- nor this\n"
        )
        assert parse_world_rules(markdown) == ("No FTL", "Inertia is never cancelled")

    def test_bold_markers_are_stripped_from_rules(self):
        assert parse_world_rules("## Rules\n- **No FTL**\n") == ("No FTL",)


class TestOutlineParsing:
    OUTLINE = (
        "# Outline\n\n## Chapters\n\n"
        "### Chapter 1 — Contact by Law\n"
        "- **POV:** Mara Kassab\n"
        "- **Tension:** 3/10\n"
        "- **Promise advanced:** Who filed the wreck?\n"
        "- **Beats:**\n  - They board.\n  - They listen.\n\n"
        "### Chapter 2 — The Cold Lamp\n"
        "- **POV:** Ilo Vega\n"
        "- **Tension:** 7/10\n"
        "- **Beats:**\n  - The lamp is warm.\n"
    )

    def test_reads_every_chapter(self):
        plans = parse_outline(self.OUTLINE)
        assert [p["number"] for p in plans] == [1, 2]
        assert plans[0]["title"] == "Contact by Law"
        assert plans[0]["pov"] == "Mara Kassab"
        assert plans[0]["tension"] == 3
        assert plans[0]["beats"] == ["They board.", "They listen."]

    def test_a_missing_field_defaults_rather_than_raising(self):
        """A thin outline entry is a quality problem, not a crash."""
        plans = parse_outline(self.OUTLINE)
        assert plans[1]["promise"] == ""
        assert plans[1]["tension"] == 7

    def test_chapters_come_back_in_order(self):
        reversed_md = "### Chapter 2 — B\n- **POV:** x\n### Chapter 1 — A\n- **POV:** y\n"
        assert [p["number"] for p in parse_outline(reversed_md)] == [1, 2]

    def test_no_chapters_yields_empty(self):
        assert parse_outline("# Outline\n\nnothing here\n") == ()


class TestStructure:
    def test_chapter_body_drops_headings(self):
        """assert_no_prior_prose compares against this, so a shared chapter
        title must never count as leaked prose."""
        assert chapter_body("# Cap 1\ntexto\n## sub\nmas") == "texto\nmas"

    def test_heading_reads_the_first_atx_heading(self):
        assert heading("# Chapter 1 — Title\n\nprose") == "Chapter 1 — Title"
        assert heading("no heading") == ""


class TestSlugify:
    def test_derives_a_slug_from_a_premise(self):
        assert slugify("A deep-space salvage crew finds a derelict that remembers them") \
            == "a-deep-space-salvage-crew-finds-a-derelict-that"

    def test_strips_accents_and_punctuation(self):
        assert slugify("Ñandú: ¡vuela!") == "nandu-vuela"

    def test_never_returns_empty(self):
        assert slugify("") == "untitled"
        assert slugify("!!!") == "untitled"

    def test_result_is_always_a_legal_slug(self):
        """It has to clear security.validation's pattern when that lands."""
        import re
        for text in ("A B C", "¡¿?!", "x" * 200, "--leading--"):
            assert re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", slugify(text)), text
