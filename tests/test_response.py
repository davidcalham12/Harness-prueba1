"""Reading a model's answer, and the three fixes that came out of doing so.

Every case here was found by running the pipeline against `tests/messy.py` —
an engine that returns what a real model returns rather than what the parsers
expect. None of it was found by reading the code.
"""

from __future__ import annotations

import pytest

from novaforge.response import (
    HEADING_KINDS,
    clean_response,
    find_chatter,
    strip_chatter,
    trim_to_first_heading,
    unwrap_code_fence,
)

CHAPTER = "# Chapter 1 — The Cold Lamp\n\nMara Kassab checked the hatch.\n"


class TestCodeFence:
    def test_a_fence_around_the_whole_answer_is_removed(self):
        assert unwrap_code_fence("```markdown\n" + CHAPTER.strip() + "\n```") == \
            CHAPTER.strip()

    @pytest.mark.parametrize("lang", ["", "markdown", "md", "text"])
    def test_any_language_tag(self, lang):
        assert "# Chapter" in unwrap_code_fence(f"```{lang}\n# Chapter 1\n```")

    def test_a_fence_around_part_of_an_answer_is_content(self):
        """A model quoting a manifest inside a chapter. Only a fence with
        nothing outside it can be packaging."""
        text = "Prose before.\n\n```\nthe manifest\n```\n\nProse after."
        assert unwrap_code_fence(text) == text

    def test_text_with_no_fence_is_untouched(self):
        assert unwrap_code_fence(CHAPTER) == CHAPTER


class TestPreamble:
    def test_anything_before_the_first_heading_goes(self):
        assert trim_to_first_heading("Certainly. Here it is:\n\n" + CHAPTER) \
            .startswith("# Chapter 1")

    def test_an_answer_with_no_heading_is_left_alone_by_default(self):
        """It may still be the answer; the parsers decide."""
        assert trim_to_first_heading("just prose") == "just prose"

    def test_required_returns_nothing_when_there_is_no_heading(self):
        assert trim_to_first_heading("just prose", required=True) == ""

    def test_the_kinds_that_are_trimmed_are_the_ones_asked_for_a_heading(self):
        assert "chapter" in HEADING_KINDS and "world" in HEADING_KINDS
        # Prose with no heading: trimming would leave nothing at all.
        assert "synopsis" not in HEADING_KINDS
        assert "summary" not in HEADING_KINDS
        assert "style" not in HEADING_KINDS


class TestFindChatter:
    @pytest.mark.parametrize("line", [
        "Let me know if you'd like me to adjust the tone.",
        "Happy to expand any section further.",
        "Certainly. Below is the chapter.",
        "Here is the cast for your novel:",
        "I kept this tight; say the word if you want it longer.",
    ])
    def test_operator_facing_text_at_an_edge_is_found(self, line):
        assert find_chatter(f"{CHAPTER}\n\n{line}")

    def test_the_same_words_in_the_middle_are_dialogue(self):
        """The reason this is a critic and not a filter. A program that deleted
        the second to catch the first would be editing an author's prose."""
        middle = (CHAPTER + "\n\n" + "\n\n".join(["Prose."] * 4)
                  + "\n\n“Let me know if the hatch holds,” she said."
                  + "\n\n" + "\n\n".join(["More prose."] * 4))
        assert find_chatter(middle) == []

    def test_a_clean_chapter_is_clean(self):
        assert find_chatter(CHAPTER) == []

    def test_it_never_modifies_the_text(self):
        text = f"{CHAPTER}\n\nHappy to expand any section further."
        find_chatter(text)
        assert text.endswith("Happy to expand any section further.")

    def test_every_finding_quotes_what_it_found(self):
        hits = find_chatter(f"{CHAPTER}\n\nLet me know if you want more.")
        assert hits and all(h["quote"] and h["kind"] for h in hits)


class TestStripChatter:
    def test_it_removes_whole_paragraphs_from_both_ends(self):
        text = ("Certainly. Below is the synopsis.\n\n"
                "A crew finds a derelict.\n\n"
                "Happy to expand any section further.")
        out, removed = strip_chatter(text)
        assert out.strip() == "A crew finds a derelict."
        assert {c["where"] for c in removed} == {"start", "end"}

    def test_clean_text_is_returned_unchanged(self):
        text = "A crew finds a derelict.\n\nIt remembers them."
        out, removed = strip_chatter(text)
        assert out.strip() == text and removed == []

    def test_it_reports_everything_it_cut(self):
        _, removed = strip_chatter("Certainly. Here it is:\n\nProse.")
        assert removed and removed[0]["quote"].startswith("Certainly")

    def test_text_that_is_chatter_throughout_is_left_visible(self):
        """Returning nothing would hide the problem instead of showing it."""
        text = "Certainly. Below is the synopsis."
        out, removed = strip_chatter(text)
        assert out == text and removed == []


class TestCleanResponse:
    def test_it_unwraps_then_trims(self):
        answer = "```markdown\nCertainly. Here it is:\n\n" + CHAPTER.strip() + "\n```"
        assert clean_response(answer, expect_heading=True).startswith("# Chapter 1")

    def test_it_does_not_remove_chatter(self):
        """The mechanical half only. The judgement is the gate's."""
        answer = CHAPTER + "\n\nHappy to expand any section further."
        assert "Happy to expand" in clean_response(answer, expect_heading=True)

    def test_an_empty_answer_stays_empty(self):
        assert clean_response("") == ""
        assert clean_response("   \n  ") == ""
