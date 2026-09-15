"""The pipeline against output that looks like a real model's.

The mock engine emits exactly the shapes the parsers expect, because the same
person wrote both sides. That is what makes `output/golden-tiny/` reproducible
and what makes it useless for asking whether this harness can read an answer it
did not author.

`tests/messy.py` wraps the mock and roughens it the way a real model varies:
a preamble, a trailing offer to revise, a ```markdown fence, `*` bullets, a
`:` where the prompt showed an em dash, `**Chapter 1**` instead of
`### Chapter 1`.

Three defects came out of this, and none of them were visible from the code:

1. `**Chapter 1 — Title**` made the outline unparseable and killed the run.
2. Model chatter was published inside `dist/book.md`, and counted by the
   Length Critic as prose.
3. The chatter arrived *after* the gate — from the style pass and the
   publisher — where nothing would have caught it.
"""

from __future__ import annotations

import re

import pytest

from conftest import PREMISE
from messy import PERTURBATIONS, MessyEngine
from novaforge.agents import load_agents
from novaforge.composition import resolve_config
from novaforge.config import package_root
from novaforge.orchestrator import Orchestrator
from novaforge.security.sandbox import Workspace
from novaforge.spec.flow import load_flow
from novaforge.textops import parse_characters, parse_outline, parse_world_rules

CHATTER_IN_BOOK = re.compile(
    r"Here is the|Certainly\.|I've put together|Let me know if|"
    r"Happy to expand|say the word|```", re.I)


def run_messy(tmp_path, *, seed=0, only=None, report=None):
    config = resolve_config(profile="tiny")
    spec = load_flow(package_root() / "specs" / "flow.yaml", config=config)
    space = Workspace(tmp_path / f"messy-{seed}")
    engine = MessyEngine(model=config.get("engine.model"), seed=seed, only=only)
    orch = Orchestrator(spec=spec, config=config, workspace=space, engine=engine,
                        premise=PREMISE, slug="m",
                        report=report or (lambda *_: None),
                        agents=load_agents(package_root()))
    return orch.run(), space


class TestItSurvivesRealisticOutput:
    @pytest.mark.parametrize("seed", [0, 1, 2, 3])
    def test_the_run_completes_with_every_variation_at_once(self, tmp_path, seed):
        state, _ = run_messy(tmp_path, seed=seed)
        assert state.stage == "complete"

    @pytest.mark.parametrize("perturbation", PERTURBATIONS)
    def test_no_single_variation_breaks_the_run(self, tmp_path, perturbation):
        """Isolated, so a failure names the one variation responsible rather
        than "something in the chain"."""
        state, _ = run_messy(tmp_path, seed=0, only=(perturbation,))
        assert state.stage == "complete"

    def test_a_bold_chapter_heading_still_parses(self, tmp_path):
        """The one that killed the run: a model answering `**Chapter 1: Title**`
        where the prompt showed `### Chapter 1 — Title`."""
        _, space = run_messy(tmp_path, only=("bold_heading_instead_of_hash",))
        assert len(parse_outline(space.read_text("outline.md"))) == 3


class TestTheCanonStaysReadable:
    """The dangerous failure is not a crash. It is a run that finishes with an
    empty cast, because then the Continuity Critic has nothing to check against
    and scores every chapter 10/10 for free."""

    @pytest.mark.parametrize("perturbation", PERTURBATIONS)
    def test_the_critics_never_go_blind(self, tmp_path, perturbation):
        _, space = run_messy(tmp_path, only=(perturbation,))
        assert len(parse_characters(space.read_text("bible/characters.md"))) >= 4
        assert len(parse_world_rules(space.read_text("bible/world.md"))) >= 4
        assert len(parse_outline(space.read_text("outline.md"))) == 3


class TestNothingModelFacingIsPublished:
    @pytest.mark.parametrize("seed", [0, 1, 2, 3])
    def test_anything_published_is_either_clean_or_declared(self, tmp_path, seed):
        """The exact contract, which is weaker than "the book is always clean"
        and is what the config actually promises.

        `quality_gate.on_fail` is `accept_with_warnings`: a chapter that never
        clears the gate ships anyway, with its warnings recorded. So the claim
        worth defending is not that nothing gets through — it is that nothing
        gets through *silently*. Asserting a spotless book would be asserting
        against the configured policy.
        """
        state, space = run_messy(tmp_path, seed=seed)
        if not CHATTER_IN_BOOK.search(space.read_text("dist/book.md")):
            return
        warned = [c for c in state.chapters if c["status"] == "accepted_with_warnings"]
        assert warned, "chatter reached the book with nothing declaring it"
        # And the warning quotes it, so a reader can find what shipped.
        assert any(CHATTER_IN_BOOK.search(w) for c in warned for w in c["warnings"]), \
            [c["warnings"] for c in warned]

    def test_a_fence_never_survives_to_the_book(self, tmp_path):
        """Unlike chatter, a fence is unambiguous and is removed mechanically,
        so there is no policy under which one may ship."""
        for seed in range(4):
            _, space = run_messy(tmp_path, seed=seed)
            assert "```" not in space.read_text("dist/book.md")

    def test_the_gate_scores_chatter_and_asks_for_the_chapter_again(self, tmp_path):
        lines: list[str] = []
        run_messy(tmp_path, seed=2, report=lines.append)
        report = "\n".join(lines)
        assert "chatter" in report
        assert "-> retry" in report

    def test_the_style_pass_discards_output_that_changed_content(self, tmp_path):
        """FLOW-5 runs after the gate, so nothing downstream would catch it.
        Its contract is that it changes nothing, so output that changed
        something is not usable and the approved draft is."""
        lines: list[str] = []
        _, space = run_messy(tmp_path, seed=0, only=("trailer",), report=lines.append)
        for number in (1, 2, 3):
            draft = space.read_text(f"chapters/ch{number:02d}.md")
            final = space.read_text(f"chapters/ch{number:02d}.final.md")
            assert len(final.split()) == len(draft.split())

    def test_chapter_word_counts_are_prose_not_padding(self, tmp_path):
        """A trailer counted as words means a chapter can clear its band on the
        strength of an apology."""
        state, _ = run_messy(tmp_path, seed=0)
        config = resolve_config(profile="tiny")
        low = config.get("novel.words_per_chapter.min")
        high = config.get("novel.words_per_chapter.max")
        assert all(low <= c["words"] <= high for c in state.chapters)


class TestTheProbeIsHonest:
    def test_the_messy_engine_is_not_selectable_from_the_cli(self):
        """It lives in tests/ because it is a probe for finding fragility, not
        something the shipped program should be able to run."""
        from novaforge.engines import EngineError, build_engine

        with pytest.raises(EngineError):
            build_engine("messy", model="claude-opus-5")

    def test_it_actually_perturbs_something(self, tmp_path):
        """A probe that quietly did nothing would make every test above pass
        for the wrong reason."""
        config = resolve_config(profile="tiny")
        engine = MessyEngine(model=config.get("engine.model"), seed=0)
        run_messy(tmp_path, seed=0)
        probe = MessyEngine(model=config.get("engine.model"), seed=0)
        from novaforge.engines.base import Request
        for kind in ("world", "characters", "outline"):
            probe.complete(Request(role="r", system="s", prompt="p",
                                   task={"kind": kind, "premise": "p", "tone": "t",
                                         "rules": 4, "technology": 3, "factions": 2,
                                         "characters": 4, "chapters": 3, "beats": 3,
                                         "promises": 3}))
        assert probe.applied, "the messy engine changed nothing at all"
