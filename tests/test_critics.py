"""The quality gate's three critics.

Each critic is tested for both directions, because a critic that never fires is
indistinguishable from one that is switched off. The Science Auditor gets a
third: it must only enforce rules the *world* actually declared, or it is
imposing its own physics on a setting that never agreed to them.
"""

from __future__ import annotations

import pytest

from novaforge.critics import CRITICS, UnknownCritic, build_critics
from novaforge.critics.base import CriticContext, score_from_findings
from novaforge.critics.continuity import ContinuityCritic, edit_distance
from novaforge.critics.length import LengthCritic
from novaforge.critics.science import ScienceCritic
from novaforge.domain.models import Finding
from novaforge.textops import Character

CAST = (Character("Mara Kassab", "pilot"), Character("Ilo Vega", "engineer"))
RULES = (
    "No faster-than-light travel. Every crossing is measured in months.",
    "Inertia is never cancelled. Thrust is felt in the spine.",
    "Vacuum kills in under two minutes, and it is silent.",
)
BANDS = {
    "words_min": 300, "words_max": 550, "words_target": 420,
    "paragraphs_min": 5, "paragraphs_max": 24,
    "lines_min": 25, "lines_max": 95, "chars_per_line_max": 64,
}


def chapter(words: int, *, text: str | None = None) -> str:
    body = text or " ".join(["palabra"] * words)
    paragraphs = "\n\n".join(
        " ".join(body.split()[i:i + 40]) for i in range(0, len(body.split()), 40))
    return "# Chapter 1 — T\n\n" + paragraphs + "\n"


def review(critic, text, *, cast=CAST, rules=RULES):
    return critic.review(CriticContext(chapter=1, text=text, characters=cast,
                                       world_rules=rules, config=BANDS))


class TestRegistry:
    def test_the_gate_names_kinds_not_agents(self):
        """Two are model-shaped, two are pure code: `length` is arithmetic
        and `chatter` is pattern matching. The gate does not care which."""
        assert set(CRITICS) == {"continuity", "science", "length", "chatter"}

    def test_building_preserves_the_configured_order(self):
        built = build_critics(["length", "continuity"])
        assert [c.name for c in built] == ["length", "continuity"]

    def test_an_unknown_critic_raises_rather_than_being_skipped(self):
        """Skipping it would silently remove a critic from the gate, and the
        gate would still pass - measuring less than it says it measures."""
        with pytest.raises(UnknownCritic):
            build_critics(["continuity", "vibes"])


class TestScoring:
    def test_a_high_finding_drops_a_draft_below_eight(self):
        assert score_from_findings([Finding("k", "high", "q", "f")]) < 8

    def test_scores_are_clamped_to_zero(self):
        assert score_from_findings([Finding("k", "high", "q", "f")] * 9) == 0

    def test_no_findings_is_ten(self):
        assert score_from_findings([]) == 10


class TestLengthCritic:
    critic = LengthCritic()

    def test_in_band_scores_ten(self):
        assert review(self.critic, chapter(420)).score == 10

    def test_too_short_is_caught_and_quoted(self):
        result = review(self.critic, chapter(100))
        assert result.score < 8
        assert result.findings[0].kind == "too-short"
        assert "100 words" in result.findings[0].quote

    def test_too_long_is_caught(self):
        assert review(self.critic, chapter(900)).findings[0].kind == "too-long"

    def test_the_finding_cites_the_config_key_that_set_the_band(self):
        assert "words_per_chapter.min" in review(self.critic, chapter(100)).findings[0].reference

    def test_lines_are_counted_as_the_manuscript_will_be_wrapped(self):
        """Not as the draft happens to be laid out - the model's newlines are
        not what a reader sees."""
        one_long_line = "# T\n\n" + " ".join(["palabra"] * 420) + "\n"
        detail = review(self.critic, one_long_line).detail
        assert detail["lines"] > 1
        assert detail["wrap_width"] == 64

    def test_detail_reports_what_was_measured(self):
        detail = review(self.critic, chapter(420)).detail
        assert detail["words"] == 420
        assert detail["paragraphs"] >= 5

    def test_it_is_pure_arithmetic_and_needs_no_canon(self):
        assert review(self.critic, chapter(420), cast=(), rules=()).score == 10


class TestContinuityCritic:
    critic = ContinuityCritic()

    def test_canonical_names_score_ten(self):
        text = chapter(0, text="Mara Kassab checked the hatch. " * 30)
        assert review(self.critic, text).score == 10

    def test_a_drifted_surname_is_caught_and_quoted(self):
        text = chapter(0, text="Mara Kassar checked the hatch. Ilo Vega waited. " * 20)
        result = review(self.critic, text)
        assert result.score < 8
        finding = result.findings[0]
        assert finding.kind == "name-drift"
        assert finding.quote == "Kassar"
        assert "Kassab" in finding.fix
        assert finding.reference == "bible/characters.md"

    def test_a_genuinely_different_name_is_not_reported_as_drift(self):
        """Past two or three edits they are different words, and reporting them
        would be noise."""
        text = chapter(0, text="Mara Kassab met Zimmerwald today. " * 30)
        assert [f.quote for f in review(self.critic, text).findings] == []

    def test_sentence_openers_are_not_mistaken_for_characters(self):
        text = chapter(0, text="The hatch closed. There was nothing. Somewhere aft. " * 20)
        assert all(f.kind != "name-drift" for f in review(self.critic, text).findings)

    def test_a_chapter_naming_nobody_is_flagged(self):
        text = chapter(0, text="The hatch closed quietly and the lamp went out. " * 20)
        assert any(f.kind == "no-canonical-character"
                   for f in review(self.critic, text).findings)

    def test_detail_lists_who_actually_appeared(self):
        text = chapter(0, text="Mara Kassab checked the hatch. " * 30)
        assert review(self.critic, text).detail["characters_present"] == ["Mara Kassab"]

    def test_it_never_reads_earlier_chapters(self):
        """Comparing chapters to each other would reintroduce the dependency
        the context policy removes."""
        assert "prior" not in CriticContext.__dataclass_fields__


class TestEditDistance:
    @pytest.mark.parametrize("a,b,expected", [
        ("Kassab", "Kassab", 0), ("Kassar", "Kassab", 1),
        ("Kassa", "Kassab", 1), ("Kassabb", "Kassab", 1),
    ])
    def test_distances(self, a, b, expected):
        assert edit_distance(a, b) == expected

    def test_it_abandons_past_the_cap(self):
        assert edit_distance("completely", "different", cap=3) > 3


class TestScienceCritic:
    critic = ScienceCritic()

    def test_compliant_prose_scores_ten(self):
        text = chapter(0, text="Mara Kassab braced against the burn. " * 30)
        assert review(self.critic, text).score == 10

    @pytest.mark.parametrize("phrase", [
        "engaged the warp drive", "entered hyperspace", "the inertial dampener held",
    ])
    def test_a_rule_break_is_caught(self, phrase):
        text = chapter(0, text=f"Mara Kassab {phrase} and waited. " * 20)
        result = review(self.critic, text)
        assert result.score < 8
        assert result.findings[0].kind == "physics-violation"

    def test_the_finding_quotes_the_whole_sentence_not_the_bare_phrase(self):
        """The writer has to be able to find it in the draft."""
        text = chapter(0, text="Mara Kassab engaged the warp drive and waited. " * 20)
        assert "Mara Kassab" in review(self.critic, text).findings[0].quote

    def test_a_world_that_permits_ftl_is_not_wrong_for_using_it(self):
        """Each check is conditional on the canon. A critic enforcing its own
        physics would be auditing a book nobody wrote."""
        text = chapter(0, text="Mara Kassab engaged the warp drive. " * 20)
        assert review(self.critic, text, rules=("Magic is real.",)).score == 10

    def test_detail_names_which_rules_were_enforced(self):
        text = chapter(0, text="Mara Kassab waited. " * 30)
        assert "faster-than-light" in review(self.critic, text).detail["rules_enforced"]

    def test_no_canon_means_nothing_to_enforce(self):
        text = chapter(0, text="Mara Kassab engaged the warp drive. " * 20)
        assert review(self.critic, text, rules=()).score == 10
