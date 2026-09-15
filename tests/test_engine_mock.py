"""The mock engine.

Two properties carry the whole offline story:

* **Determinism across processes.** ``output/golden-tiny/`` is a fixture you
  diff. An engine that was deterministic within a run and different on the next
  one would make every diff meaningless, which is exactly what seeding from
  ``hash()`` would have done - Python randomises string hashing per process.
* **The deliberate drift.** A run where every chapter passes first time would
  demonstrate nothing about the gate.
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter

import pytest

from novaforge.engines import EngineError, build_engine
from novaforge.engines.base import Request
from novaforge.engines.mock import MockEngine, _drifted
from novaforge.textops import (
    chapter_body,
    count_words,
    parse_characters,
    parse_world_rules,
)

NAMES = ["Mara Kassab", "Ilo Vega"]


def ask(engine, kind, **task):
    return engine.complete(Request(role="r", system="s", prompt="p",
                                   task={"kind": kind, **task})).text


class TestRegistry:
    def test_mock_is_built_by_name(self, config):
        assert build_engine("mock", model="claude-opus-5").name == "mock"

    def test_an_unknown_engine_raises_rather_than_falling_back(self):
        """A typo in --engine must not silently produce a free, fake novel
        that looks real."""
        with pytest.raises(EngineError, match="unknown engine"):
            build_engine("mokc", model="claude-opus-5")

    def test_the_anthropic_engine_reports_its_absence_clearly(self):
        with pytest.raises(EngineError, match="not implemented"):
            build_engine("anthropic", model="claude-opus-5")


class TestDeterminism:
    def test_two_engines_with_the_same_seed_agree(self, engine, config):
        other = build_engine("mock", model=config.get("engine.model"),
                            seed=config.get("engine.seed"), inject_drift=True)
        assert ask(engine, "chapter", chapter=1, iteration=1, target_words=420,
                   names=NAMES) == \
            ask(other, "chapter", chapter=1, iteration=1, target_words=420, names=NAMES)

    def test_different_seeds_differ(self, config):
        a = build_engine("mock", model="claude-opus-5", seed=0)
        b = build_engine("mock", model="claude-opus-5", seed=1)
        assert ask(a, "chapter", chapter=1, iteration=1, target_words=420, names=NAMES) != \
            ask(b, "chapter", chapter=1, iteration=1, target_words=420, names=NAMES)

    def test_determinism_survives_a_fresh_interpreter(self):
        """The regression that matters: seeding from hash() passes every
        in-process check and fails this one."""
        code = (
            "from novaforge.engines import build_engine;"
            "from novaforge.engines.base import Request;"
            "e=build_engine('mock',model='claude-opus-5',seed=0);"
            "print(len(e.complete(Request(role='r',system='s',prompt='p',"
            "task={'kind':'chapter','chapter':1,'iteration':1,'target_words':420,"
            "'names':['Mara Kassab','Ilo Vega']})).text))"
        )
        outputs = {
            subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, check=True).stdout.strip()
            for _ in range(2)
        }
        assert len(outputs) == 1


class TestArtefactShapes:
    def test_the_world_parses_back_into_rules(self, engine):
        text = ask(engine, "world", premise="p", tone="hard-scifi",
                   rules=4, technology=3, factions=2)
        assert len(parse_world_rules(text)) == 4

    def test_the_cast_parses_back_into_characters(self, engine):
        assert len(parse_characters(ask(engine, "characters", characters=4))) == 4

    def test_the_outline_has_one_entry_per_chapter(self, engine):
        from novaforge.textops import parse_outline
        plans = parse_outline(ask(engine, "outline", chapters=3, beats=3,
                                  promises=3, characters=4))
        assert [p["number"] for p in plans] == [1, 2, 3]
        assert all(p["beats"] for p in plans)

    def test_the_tension_curve_is_not_flat(self, engine):
        from novaforge.textops import parse_outline
        plans = parse_outline(ask(engine, "outline", chapters=8, beats=3,
                                  promises=3, characters=4))
        assert len({p["tension"] for p in plans}) > 1

    def test_a_chapter_opens_with_a_single_heading(self, engine):
        text = ask(engine, "chapter", chapter=1, iteration=1, target_words=420, names=NAMES)
        assert text.startswith("# Chapter 1 —")
        assert text.count("\n# ") == 0

    def test_a_chapter_lands_near_its_target(self, engine):
        words = count_words(ask(engine, "chapter", chapter=1, iteration=1,
                                target_words=420, names=NAMES))
        assert 420 <= words <= 420 * 1.15

    def test_an_unknown_task_kind_is_refused(self, engine):
        with pytest.raises(EngineError, match="no generator"):
            ask(engine, "haiku")


class TestVariety:
    """The mock is not trying to write well, but it must not look broken.

    Before this was fixed, picking a template at random each time meant the
    same sentence appeared eight times in a three-chapter book, twice of them
    back to back in the same paragraph. A reader seeing that concludes the
    harness is broken, whatever it is actually doing.
    """

    @staticmethod
    def sentences(text):
        import re

        from novaforge.engines.mock import _SENTENCE_BREAK

        flat = " ".join(chapter_body(text).split())
        return [s.strip() for s in re.split(_SENTENCE_BREAK, flat)
                if s and len(s.split()) > 4]

    @pytest.mark.parametrize("target", [420, 1150, 2000, 2700])
    def test_no_sentence_repeats_within_a_chapter(self, engine, target):
        """Checked at every profile's length. The `full` profile is the one
        that matters: a 190-sentence chapter exhausts the combinations, and
        that is where an earlier fix still left eleven repeats."""
        text = ask(engine, "chapter", chapter=1, iteration=1,
                   target_words=target, names=NAMES)
        lines = self.sentences(text)
        duplicates = [s for s, n in Counter(lines).items() if n > 1]
        assert duplicates == [], duplicates

    def test_no_sentence_ever_follows_itself(self, engine):
        lines = self.sentences(ask(engine, "chapter", chapter=1, iteration=1,
                                   target_words=2700, names=NAMES))
        assert not [a for a, b in zip(lines, lines[1:]) if a == b]

    def test_every_template_renders_differently_each_time(self):
        """A template with no placeholder renders identically for ever, so it
        can only appear once per chapter and then repeats across chapters.
        Each half of a two-sentence template needs a slot too."""
        import re

        from novaforge.engines.mock import _SENTENCE_BREAK, _SENTENCES

        for template in _SENTENCES:
            for part in re.split(_SENTENCE_BREAK, template):
                if part and len(part.split()) > 3:
                    assert "{" in part, template

    def test_variety_never_costs_length(self, engine):
        """Length is a hard requirement and novelty is best-effort. A chapter
        that came out short to stay varied would fail the gate for the wrong
        reason."""
        for target in (420, 2700):
            words = count_words(ask(engine, "chapter", chapter=1, iteration=1,
                                    target_words=target, names=NAMES))
            assert target <= words <= target * 1.15


class TestDrift:
    def test_even_chapters_drift_on_the_first_draft(self, engine):
        text = ask(engine, "chapter", chapter=2, iteration=1, target_words=420, names=NAMES)
        assert "Kassar" in text or "Vege" in text

    def test_the_rewrite_comes_back_clean(self, engine):
        text = ask(engine, "chapter", chapter=2, iteration=2, target_words=420, names=NAMES)
        assert "Kassar" not in text

    def test_odd_chapters_never_drift(self, engine):
        for number in (1, 3, 5):
            text = ask(engine, "chapter", chapter=number, iteration=1,
                       target_words=420, names=NAMES)
            assert "Kassar" not in text

    def test_drift_can_be_switched_off(self):
        clean = build_engine("mock", model="claude-opus-5", seed=0, inject_drift=False)
        text = ask(clean, "chapter", chapter=2, iteration=1, target_words=420, names=NAMES)
        assert "Kassar" not in text

    def test_the_misspelling_is_one_edit_away(self):
        """The shape of a transcription error, not a different name."""
        from novaforge.critics.continuity import edit_distance
        assert edit_distance(_drifted("Kassab"), "Kassab") == 1


class TestUsage:
    def test_every_completion_reports_tokens_and_a_model(self, engine, config):
        completion = engine.complete(Request(role="r", system="s", prompt="p",
                                             task={"kind": "characters", "characters": 4}))
        assert completion.model == config.get("engine.model")
        assert completion.usage.input_tokens > 0
        assert completion.usage.output_tokens > 0
        assert completion.usage.total_tokens == (completion.usage.input_tokens
                                                 + completion.usage.output_tokens)

    def test_the_mock_reports_the_same_model_id_as_a_real_run(self, engine):
        """So a dry run produces a cost estimate with the same arithmetic."""
        from novaforge.pricing import is_known_model
        assert is_known_model(engine.model)


class TestStylePass:
    def test_it_does_not_change_the_word_count(self, engine):
        """A style pass that rewrote sentences would invalidate the critique
        the chapter just passed."""
        original = ask(engine, "chapter", chapter=1, iteration=1,
                       target_words=420, names=NAMES)
        assert count_words(ask(engine, "style", text=original)) == count_words(original)


class TestSummary:
    def test_the_summary_is_extractive(self, engine):
        """Which is why assert_no_prior_prose is told to skip it."""
        chapter_text = ask(engine, "chapter", chapter=1, iteration=1,
                           target_words=420, names=NAMES)
        summary = ask(engine, "summary", chapter=1, text=chapter_text)
        assert summary
        assert summary.split(".")[0] in chapter_text

    def test_an_empty_chapter_summarises_to_nothing(self, engine):
        assert ask(engine, "summary", chapter=1, text="") == ""
