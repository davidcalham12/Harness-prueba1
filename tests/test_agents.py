"""The agent layer: skills, specs, and the requirements they declare.

Every ``AGT-XX-N`` in ``specs/agents/`` is cited by a docstring below, and
``tools/check_specs.py`` fails if one is not. That is the whole point of the
identifiers: a requirement with no test is a promise the project is not keeping
and does not know it.
"""

from __future__ import annotations

import json

import pytest

from conftest import PREMISE, run_novel
from novaforge.agents import Agent, AgentError, load_agents
from novaforge.config import package_root
from novaforge.textops import count_words, parse_characters, parse_outline, parse_world_rules

STAGE_AGENTS = ("worldbuilder", "character_architect", "plot_architect",
                "chapter_writer", "style_editor", "publisher")
CRITIC_AGENTS = ("continuity_critic", "science_critic")


@pytest.fixture(scope="module")
def registry():
    return load_agents(package_root())


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    lines: list[str] = []
    orch, state, space = run_novel(tmp_path_factory.mktemp("agents"),
                                   report=lines.append)
    return orch, state, space, lines


class TestTheRegistry:
    def test_eight_agents_eight_skills(self, registry):
        """The count the RUNBOOK's spec checker reports."""
        assert len(registry) == 8
        assert {a.name for a in registry} == set(STAGE_AGENTS) | set(CRITIC_AGENTS)

    def test_every_stage_in_the_flow_has_an_agent(self, registry, flow):
        for stage in flow:
            assert registry.get(stage.agent).role == stage.agent

    def test_an_unknown_role_says_where_to_put_the_file(self, registry):
        with pytest.raises(AgentError, match="SKILL.md"):
            registry.get("chief_vibes_officer")

    def test_two_of_the_eight_are_declared_off_the_shipping_path(self, registry):
        """Declared, not discovered. An unused prompt nobody has marked unused
        is a prompt everyone assumes is running."""
        parked = {a.name for a in registry if not a.on_shipping_path}
        assert parked == set(CRITIC_AGENTS)
        assert {a.name for a in registry.shipping} == set(STAGE_AGENTS)

    def test_a_missing_skills_directory_does_not_fall_back(self, tmp_path):
        with pytest.raises(AgentError, match="no built-in prompts"):
            load_agents(tmp_path)


class TestAuthority:
    def test_only_two_skills_claim_bible_authority(self, registry):
        claiming = {a.name for a in registry if a.writes_bible}
        assert claiming == {"worldbuilder", "character_architect"}

    def test_the_registry_is_checked_against_the_flow_spec(self, registry, flow):
        registry.check_against_flow(flow)

    def test_a_skill_cannot_promote_itself(self, registry, flow):
        """SEC-4.3: authority comes from the spec, not from a file's own front
        matter. Otherwise editing one Markdown file would grant Bible access."""
        promoted = dict({a.role: a for a in registry})
        promoted["publisher"] = Agent(
            name="publisher", role="publisher", model="claude-sonnet-5",
            writes_bible=True, prompt="x", spec_path="s", source="fake",
        )
        from novaforge.agents import AgentRegistry
        forged = AgentRegistry(promoted, root=package_root())
        with pytest.raises(AgentError, match="Authority comes from the spec"):
            forged.check_against_flow(flow)


class TestPromptLoading:
    def test_prompts_come_from_the_skill_files_not_from_python(self, registry):
        """novaforge/__init__.py promises no prompt lives in this package's
        source. This is that promise, checked."""
        import inspect
        from novaforge.stages import bible_sections, chapters, outline, publish, style

        for module in (bible_sections, chapters, outline, publish, style):
            source = inspect.getsource(module)
            assert "You are the" not in source, module.__name__

    def test_every_stage_asks_its_agent_for_the_prompt(self):
        import inspect
        from novaforge.stages import bible_sections, chapters, outline, publish, style

        for module in (bible_sections, chapters, outline, publish, style):
            assert "context.agent.system(" in inspect.getsource(module)

    def test_a_missing_placeholder_raises_rather_than_reaching_the_model(self, registry):
        """'a {tone} novel' sent verbatim reads as a strange instruction and is
        invisible in the output."""
        agent = registry.get("style_editor")
        assert "tone" in agent.placeholders
        with pytest.raises(AgentError, match="tone"):
            agent.system()

    def test_placeholders_are_filled(self, registry):
        filled = registry.get("style_editor").system(tone="hard-scifi")
        assert "hard-scifi" in filled and "{tone}" not in filled

    def test_the_chapter_writer_carries_the_untrusted_clause(self, registry):
        from novaforge.security.prompting import UNTRUSTED_CLAUSE

        agent = registry.get("chapter_writer")
        assert "untrusted_clause" in agent.placeholders
        filled = agent.system(tone="t", number=1, title="T", target_words=400,
                              untrusted_clause=UNTRUSTED_CLAUSE)
        assert UNTRUSTED_CLAUSE in filled


class TestMalformedSkills:
    def _write(self, tmp_path, text, name="worldbuilder"):
        path = tmp_path / ".claude" / "skills" / name
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(text, encoding="utf-8")
        return tmp_path

    def test_no_front_matter_is_refused(self, tmp_path):
        self._write(tmp_path, "# Just a heading\n")
        with pytest.raises(AgentError, match="front matter"):
            load_agents(tmp_path)

    def test_a_missing_prompt_section_is_refused(self, tmp_path):
        self._write(tmp_path, "---\nname: worldbuilder\nrole: worldbuilder\n"
                              "spec: s\n---\n\n# Title\n")
        with pytest.raises(AgentError, match="System prompt"):
            load_agents(tmp_path)

    def test_a_name_disagreeing_with_its_directory_is_refused(self, tmp_path):
        self._write(tmp_path, "---\nname: publisher\nrole: publisher\nspec: s\n---\n\n"
                              "## System prompt\n\nx\n")
        with pytest.raises(AgentError, match="the directory is the address"):
            load_agents(tmp_path)

    def test_an_empty_prompt_is_refused(self, tmp_path):
        self._write(tmp_path, "---\nname: worldbuilder\nrole: worldbuilder\n"
                              "spec: s\n---\n\n## System prompt\n\n")
        with pytest.raises(AgentError, match="empty"):
            load_agents(tmp_path)


# ---------------------------------------------------------------------------
# The declared requirements, one test each.
# ---------------------------------------------------------------------------

class TestWorldbuilder:
    def test_writes_only_the_world_section(self, run):
        """AGT-WB-1 — Writes bible/world.md and nothing else."""
        _, _, space, _ = run
        rows = [json.loads(l) for l in space.read_lines("logs/agents.jsonl")]
        written = [r["section"] for r in rows
                   if r["event"] == "bible_write" and r["role"] == "worldbuilder"]
        assert written == ["world"]

    def test_declares_the_configured_number_of_rules(self, run, config):
        """AGT-WB-2 — Declares at least `bible.world_rules.min` rules under a
        `## Rules` heading."""
        _, _, space, _ = run
        world = space.read_text("bible/world.md")
        assert "## Rules" in world
        assert len(parse_world_rules(world)) >= config.get("bible.world_rules.min")


class TestCharacterArchitect:
    def test_writes_its_three_sections_in_order(self, run):
        """AGT-CA-1 — Writes characters, timeline and mysteries, in that order."""
        _, _, space, _ = run
        rows = [json.loads(l) for l in space.read_lines("logs/agents.jsonl")]
        written = [r["section"] for r in rows if r["event"] == "bible_write"
                   and r["role"] == "character_architect"]
        assert written == ["characters", "timeline", "mysteries"]

    def test_the_cast_parses_back(self, run, config):
        """AGT-CA-2 — Cast entries parse as `- **Full Name** — role; traits`."""
        _, _, space, _ = run
        cast = parse_characters(space.read_text("bible/characters.md"))
        assert len(cast) >= config.get("bible.characters.min")
        assert all(c.name and c.surname for c in cast)


class TestPlotArchitect:
    def test_one_entry_per_chapter_numbered_without_gaps(self, run, config):
        """AGT-PA-1 — Produces exactly `novel.chapters` entries, numbered from
        1 with no gaps."""
        _, _, space, _ = run
        plans = parse_outline(space.read_text("outline.md"))
        assert [p["number"] for p in plans] == list(
            range(1, config.get("novel.chapters") + 1))

    def test_every_entry_carries_pov_tension_and_beats(self, run):
        """AGT-PA-2 — Every entry carries POV, tension and beats."""
        _, _, space, _ = run
        for plan in parse_outline(space.read_text("outline.md")):
            assert plan["pov"], plan
            assert 1 <= plan["tension"] <= 10, plan
            assert plan["beats"], plan


class TestChapterWriter:
    def test_never_receives_prior_chapter_prose(self, run):
        """AGT-CW-1 — Never receives prior chapter prose.

        Enforced at runtime inside the stage, so a completed run is the proof;
        the guard's own failure path is covered in tests/test_context.py."""
        _, state, space, _ = run
        assert state.stage == "complete"
        from novaforge.context import ContextPolicyViolation, assert_no_prior_prose
        stolen = " ".join(space.read_text("chapters/ch01.md").split()[5:25])
        with pytest.raises(ContextPolicyViolation):
            assert_no_prior_prose(stolen, [space.read_text("chapters/ch01.md")])

    def test_a_rewrite_is_given_the_findings_that_rejected_it(self, run):
        """AGT-CW-2 — Receives the previous draft's findings on a rewrite, each
        quoting its text."""
        _, _, space, _ = run
        critique = space.read_json("critiques/ch02.continuity.json")
        first = critique["iterations"][0]["findings"][0]
        assert first["quote"] and first["fix"]
        from novaforge.context import build_chapter_context
        from novaforge.domain.models import ChapterPlan, Finding
        block = build_chapter_context(
            bible_context="B",
            plan=ChapterPlan(2, "T", "P", 5, "pr", ("b",)),
            summary_so_far="",
            findings=[Finding(**first)],
        ).findings_block
        assert first["quote"] in block


class TestStyleEditor:
    def test_does_not_change_the_word_count(self, run, config):
        """AGT-SE-1 — Does not change the word count of a chapter."""
        _, _, space, _ = run
        for number in range(1, config.get("novel.chapters") + 1):
            draft = space.read_text(f"chapters/ch{number:02d}.md")
            final = space.read_text(f"chapters/ch{number:02d}.final.md")
            assert count_words(draft) == count_words(final)

    def test_keeps_the_approved_draft_alongside_the_final(self, run, config):
        """AGT-SE-2 — Writes chapters/chNN.final.md without destroying the
        approved draft."""
        _, _, space, _ = run
        for number in range(1, config.get("novel.chapters") + 1):
            assert space.exists(f"chapters/ch{number:02d}.md")
            assert space.exists(f"chapters/ch{number:02d}.final.md")


class TestPublisher:
    def test_writes_the_synopsis_while_code_assembles_the_book(self, run):
        """AGT-PB-1 — Writes the synopsis; code assembles the manuscript."""
        _, _, space, _ = run
        rows = [json.loads(l) for l in space.read_lines("logs/agents.jsonl")]
        publisher_calls = [r["kind"] for r in rows
                           if r["event"] == "call" and r["role"] == "publisher"]
        assert publisher_calls == ["synopsis"]
        assert space.exists("dist/book.md") and space.exists("dist/book.pdf")

    def test_an_unwritable_format_is_reported_by_name(self, tmp_path):
        """AGT-PB-2 — A configured format with no exporter is reported by
        name."""
        lines: list[str] = []
        _, state, _ = run_novel(tmp_path, slug="fmt2", report=lines.append,
                                overrides={"outputs": {"formats": ["markdown", "vellum"]}})
        assert any("vellum" in note for note in state.notes)


class TestContinuityCritic:
    def test_reports_a_drifted_name_and_quotes_it(self, run):
        """AGT-CC-1 — Reports a name one edit from a canonical one, quoting
        it."""
        _, _, space, _ = run
        finding = space.read_json("critiques/ch02.continuity.json")["iterations"][0]["findings"][0]
        assert finding["kind"] == "name-drift"
        assert finding["quote"] == "Kassar"
        assert "Kassab" in finding["fix"]

    def test_judges_against_the_bible_never_against_earlier_chapters(self):
        """AGT-CC-2 — Judges against the Story Bible, never against earlier
        chapters."""
        from novaforge.critics.base import CriticContext
        assert "prior_chapters" not in CriticContext.__dataclass_fields__
        assert "characters" in CriticContext.__dataclass_fields__


class TestScienceCritic:
    def test_only_enforces_rules_the_world_declared(self):
        """AGT-SC-1 — Only enforces rules the world actually declared."""
        from novaforge.critics.base import CriticContext
        from novaforge.critics.science import ScienceCritic
        from novaforge.textops import Character

        draft = "# C\n\nMara Kassab engaged the warp drive and waited.\n"
        permissive = CriticContext(chapter=1, text=draft,
                                   characters=(Character("Mara Kassab"),),
                                   world_rules=("Magic is real.",), config={})
        strict = CriticContext(chapter=1, text=draft,
                               characters=(Character("Mara Kassab"),),
                               world_rules=("No faster-than-light travel.",), config={})
        assert ScienceCritic().review(permissive).score == 10
        assert ScienceCritic().review(strict).score < 8

    def test_quotes_the_whole_sentence(self):
        """AGT-SC-2 — Quotes the whole offending sentence, not the phrase."""
        from novaforge.critics.base import CriticContext
        from novaforge.critics.science import ScienceCritic

        draft = "# C\n\nMara Kassab engaged the warp drive and waited.\n"
        result = ScienceCritic().review(CriticContext(
            chapter=1, text=draft, characters=(),
            world_rules=("No faster-than-light travel.",), config={}))
        quote = result.findings[0].quote
        assert quote.startswith("Mara Kassab") and quote.endswith(".")
