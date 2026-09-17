"""Where an agent's prompt comes from, after the move to Langfuse.

The prompts are managed in Langfuse now; the SKILL.md files stayed as the
fallback and as what `tools/check_specs.py` reads. What these tests defend is
the boundary between the two — specifically that **only wording moved**.

Whether an agent may write the Story Bible is decided by `specs/flow.yaml` and
by the code. A prompt service that could grant Bible access by editing a prompt
would make SEC-4.3 a suggestion, so `Agent.with_source` replaces one field and
nothing else.
"""

from __future__ import annotations

import pytest

from novaforge.agents import load_agents
from novaforge.config import load_config, package_root
from novaforge.prompts import FilePrompts, build_prompt_source


@pytest.fixture(scope="module")
def agents():
    return load_agents(package_root())


class TestTheSource:
    @pytest.mark.parametrize("name", [None, "", "file", "skill", "local"])
    def test_every_way_of_saying_the_files(self, name):
        assert isinstance(build_prompt_source(name), FilePrompts)

    def test_an_unknown_source_raises_rather_than_guessing(self):
        with pytest.raises(ValueError, match="unknown prompt source"):
            build_prompt_source("s3")

    def test_the_shipped_config_uses_langfuse(self):
        """CFG-12 — the prompts have moved to Langfuse. The files remain
        the fallback and what check_specs.py reads."""
        assert load_config().get("agents.prompt_source") == "langfuse"
        assert load_config().get("agents.prompt_label") == "production"

    def test_the_file_source_returns_the_skill_prompt_unchanged(self, agents):
        agent = agents.get("worldbuilder")
        assert FilePrompts().get("worldbuilder", agent.prompt) == agent.prompt


class TestOnlyWordingMoves:
    def test_authority_is_never_taken_from_the_source(self, agents):
        """CFG-12 and SEC-4.3. The one thing this seam must not carry."""
        source = _Hostile()
        moved = agents.get("publisher").with_source(source)
        assert moved.writes_bible is False
        assert moved.role == "publisher"
        assert moved.name == "publisher"

    def test_the_model_is_not_taken_from_the_source_either(self, agents):
        before = agents.get("style_editor")
        after = before.with_source(_Hostile())
        assert after.model == before.model

    def test_the_wording_does_move(self, agents):
        after = agents.get("style_editor").with_source(_Hostile())
        assert "hostile" in after.prompt

    def test_the_new_provenance_is_recorded(self, agents):
        """So a run can say where its wording came from, which matters once it
        is no longer the file sitting next to the spec."""
        after = agents.get("style_editor").with_source(_Hostile())
        assert "SKILL.md" in after.source and "hostile" in after.source

    def test_an_unchanged_prompt_leaves_the_agent_alone(self, agents):
        before = agents.get("worldbuilder")
        assert before.with_source(FilePrompts()) is before

    def test_the_whole_registry_can_be_repointed(self, agents):
        moved = agents.with_prompt_source(_Hostile())
        assert len(moved) == len(agents)
        assert {a.name for a in moved} == {a.name for a in agents}
        assert all(a.writes_bible == agents.get(a.role).writes_bible for a in moved)

    def test_authority_is_checked_before_the_source_is_applied(self):
        """build_run validates against the flow spec first, so a prompt source
        can never be the thing that decides whether a skill was allowed."""
        import inspect

        from novaforge import composition

        source = inspect.getsource(composition.build_run)
        assert source.index("check_against_flow") < source.index("with_prompt_source")


class TestDegradingWithoutCredentials:
    def test_no_credentials_means_the_files_and_a_line_saying_so(self, monkeypatch):
        """Configured but unusable is the same condition as unreachable. An
        earlier version raised here while `get` fell back, so the same problem
        killed a run or did not depending on when it happened."""
        pytest.importorskip("langfuse")
        from novaforge.prompts import LangfusePrompts

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        said: list[str] = []
        source = LangfusePrompts(report=said.append)
        assert source.get("worldbuilder", "the fallback") == "the fallback"
        assert said and "SKILL.md" in said[0]

    def test_a_run_still_completes_with_no_credentials(self, tmp_path, monkeypatch):
        from conftest import run_novel

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        _, state, space = run_novel(tmp_path, slug="nokeys")
        assert state.stage == "complete"
        assert space.exists("dist/book.md")


class _Hostile:
    """A source that returns different wording and tries to claim more."""

    name = "hostile"
    writes_bible = True
    role = "worldbuilder"

    def get(self, agent_name: str, default: str) -> str:
        return f"a hostile prompt for {agent_name}"

    def describe(self, agent_name: str) -> str:
        return "hostile:source"
