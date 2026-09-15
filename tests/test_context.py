"""FLOW-4 ``context_policy`` - what the Chapter Writer is allowed to see.

This is the architectural claim of the whole project, so the tests state the
guarantee in its exact form: *no run of ten consecutive words from an earlier
chapter reaches the writer, unless that run is also in the canon the writer is
entitled to see.*

Both halves matter. Without the canon exemption, a chapter that quotes a rule
from ``world.md`` would make that rule un-quotable for every later chapter.
"""

from __future__ import annotations

import pytest

from novaforge.context import (
    LEAK_WINDOW,
    ContextPolicyViolation,
    assert_no_prior_prose,
    build_chapter_context,
    roll_summary,
)
from novaforge.domain.models import ChapterPlan, Finding

PLAN = ChapterPlan(2, "El eco", "Vega", 7, "quien recuerda", ("llegan", "escuchan", "huyen"))
PRIOR = "# Capitulo 1\n" + " ".join(f"w{i}" for i in range(40))
LEAK = " ".join(f"w{i}" for i in range(5, 5 + LEAK_WINDOW))


class TestRollSummary:
    def test_below_the_cap_everything_is_kept(self):
        assert roll_summary(["a b c", "d e"], 10) == "a b c d e"

    def test_truncation_drops_the_oldest_first(self):
        """The chapter immediately before this one is dropped last."""
        assert roll_summary(["uno dos tres", "cuatro cinco"], 2) == "cuatro cinco"

    def test_empty_and_none_are_tolerated(self):
        assert roll_summary([], 10) == ""
        assert roll_summary([None, "x"], 10) == "x"


class TestBuildContext:
    def test_the_summary_is_capped(self):
        context = build_chapter_context(bible_context="B", plan=PLAN,
                                        summary_so_far="una dos tres cuatro cinco",
                                        max_summary_words=3)
        assert context.summary_words == 3

    def test_the_plan_is_wrapped_as_untrusted(self):
        context = build_chapter_context(bible_context="B", plan=PLAN, summary_so_far="")
        assert '<untrusted source="outline.md#chapter-02">' in context.plan_block

    def test_the_plan_carries_pov_tension_promise_and_beats(self):
        block = build_chapter_context(bible_context="B", plan=PLAN,
                                      summary_so_far="").plan_block
        for expected in ("Vega", "7/10", "quien recuerda", "llegan", "huyen"):
            assert expected in block

    def test_the_first_chapter_is_marked_explicitly(self):
        rendered = build_chapter_context(bible_context="B", plan=PLAN,
                                         summary_so_far="").render()
        assert "(this is the first chapter)" in rendered

    def test_render_can_exclude_the_summary(self):
        context = build_chapter_context(bible_context="B", plan=PLAN,
                                        summary_so_far="Antes ocurrio esto")
        assert "Antes ocurrio esto" in context.render()
        assert "Antes ocurrio esto" not in context.render(include_summary=False)


class TestFindings:
    def test_findings_reach_the_writer_with_severity_quote_and_fix(self):
        finding = Finding("name-drift", "high", "Kassar", "usar Kassab",
                          "bible/characters.md")
        block = build_chapter_context(bible_context="B", plan=PLAN, summary_so_far="s",
                                      findings=[finding]).findings_block
        assert "[high] name-drift" in block
        assert "usar Kassab" in block
        assert "'Kassar'" in block
        assert "bible/characters.md" in block

    def test_no_findings_means_no_block(self):
        context = build_chapter_context(bible_context="B", plan=PLAN, summary_so_far="s")
        assert context.findings_block == ""


class TestNoPriorProse:
    def test_a_ten_word_run_is_caught(self):
        with pytest.raises(ContextPolicyViolation, match="leaked"):
            assert_no_prior_prose(f"prompt {LEAK} fin", [PRIOR])

    def test_nine_words_do_not_trip_it(self):
        """Long enough that a repeated name or stock phrase is not a leak."""
        short = " ".join(f"w{i}" for i in range(5, 5 + LEAK_WINDOW - 1))
        assert_no_prior_prose(f"prompt {short} fin", [PRIOR])

    def test_a_clean_prompt_passes(self):
        assert_no_prior_prose("nothing in common at all", [PRIOR])

    def test_canon_is_exempt(self):
        """A chapter that quotes a world rule must not make that rule
        un-quotable for every later chapter."""
        assert_no_prior_prose(f"prompt {LEAK}", [PRIOR], canon=LEAK)

    def test_headings_are_not_prose(self):
        assert_no_prior_prose("# Capitulo 1", ["# Capitulo 1"])

    def test_line_breaks_do_not_hide_a_leak(self):
        with pytest.raises(ContextPolicyViolation):
            assert_no_prior_prose(LEAK.replace(" ", "\n"), [PRIOR])

    def test_the_window_has_a_floor_of_three(self):
        """A window of one would report every shared word."""
        with pytest.raises(ContextPolicyViolation):
            assert_no_prior_prose("w5 w6 w7", [PRIOR], window=1)

    def test_a_chapter_shorter_than_the_window_is_skipped(self):
        assert_no_prior_prose("anything", ["# T\nshort"], window=10)

    def test_the_error_names_the_chapter_and_quotes_the_run(self):
        with pytest.raises(ContextPolicyViolation) as exc:
            assert_no_prior_prose(f"x {LEAK}", [PRIOR])
        assert "chapter 1" in str(exc.value)
        assert "w5" in str(exc.value)
