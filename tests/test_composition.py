"""The composition root.

The point of this module having its own tests is the thing it makes possible:
starting a run **without going through argparse**. A CLI is where flags are
parsed and exit codes are chosen; a test, a notebook or a web handler should
not have to impersonate one to run the pipeline.

So these tests call `build_run` directly, and there is one asserting that
`cli.py` no longer constructs anything itself — otherwise the two would drift
and the CLI path would quietly become the only one that works.
"""

from __future__ import annotations

import inspect

import pytest

from conftest import PREMISE, isolated_root
from novaforge.agents import AgentError
from novaforge.composition import Run, build_run, redactor_for_output, resolve_config
from novaforge.config import ConfigError
from novaforge.engines import EngineError
from novaforge.security.validation import ValidationError


@pytest.fixture
def root(tmp_path):
    return isolated_root(tmp_path)


class TestResolveConfig:
    def test_it_builds_a_config_from_a_profile(self, root):
        config = resolve_config(profile="tiny", root=root)
        assert config.get("novel.chapters") == 3

    def test_overrides_layer_on_top(self, root):
        config = resolve_config(profile="tiny", overrides={"novel": {"chapters": 2}},
                                root=root)
        assert config.get("novel.chapters") == 2

    def test_an_unknown_profile_raises(self, root):
        with pytest.raises(ConfigError):
            resolve_config(profile="enormous", root=root)

    def test_resuming_recovers_the_config_from_the_snapshot(self, root):
        """A resumed run must be the same novel. Forgetting `--profile tiny`
        must not continue a three-chapter book as a twelve-chapter one."""
        run = build_run(premise=PREMISE, config=resolve_config(profile="tiny", root=root),
                        slug="snap", root=root, report=lambda *_: None)
        run.execute()
        recovered = resolve_config(root=root, resume_slug="snap")
        assert recovered.get("novel.chapters") == 3
        assert recovered.hash == run.config.hash

    def test_resuming_a_run_that_does_not_exist_raises(self, root):
        with pytest.raises(FileNotFoundError, match="nothing to resume"):
            resolve_config(root=root, resume_slug="absent")

    def test_an_edited_snapshot_is_refused(self, root):
        """It carries its own hash; a file that disagrees with it has been
        changed by hand."""
        import json

        run = build_run(premise=PREMISE, config=resolve_config(profile="tiny", root=root),
                        slug="edited", root=root, report=lambda *_: None)
        run.execute()
        path = root / "output" / "edited" / "config.snapshot.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["resolved"]["novel"]["chapters"] = 99
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ValueError, match="its own hash"):
            resolve_config(root=root, resume_slug="edited")


class TestBuildRun:
    def test_it_returns_everything_already_wired(self, root):
        run = build_run(premise=PREMISE, config=resolve_config(profile="tiny", root=root),
                        slug="wired", root=root, report=lambda *_: None)
        assert isinstance(run, Run)
        assert run.slug == "wired"
        assert run.engine.name == "mock"
        assert len(run.agents) == 8
        assert len(run.spec) == 6
        assert run.out_dir == run.workspace.root

    def test_the_slug_is_derived_from_the_premise_when_absent(self, root):
        run = build_run(premise=PREMISE, config=resolve_config(profile="tiny", root=root),
                        root=root, report=lambda *_: None)
        assert run.slug == "a-deep-space-salvage-crew-finds-a-derelict-that"

    def test_a_run_executes_without_any_cli(self, root):
        """The reason this module exists."""
        run = build_run(premise=PREMISE, config=resolve_config(profile="tiny", root=root),
                        slug="api", root=root, report=lambda *_: None)
        state = run.execute()
        assert state.stage == "complete"
        assert len(state.chapters) == 3
        assert run.workspace.exists("dist/book.md")

    def test_the_engine_can_be_overridden(self, root):
        run = build_run(premise=PREMISE, config=resolve_config(profile="tiny", root=root),
                        slug="eng", engine_name="mock", root=root, report=lambda *_: None)
        assert run.engine.name == "mock"

    def test_an_unknown_engine_raises_before_anything_is_built(self, root):
        with pytest.raises(EngineError):
            build_run(premise=PREMISE, config=resolve_config(profile="tiny", root=root),
                      slug="bad", engine_name="mokc", root=root, report=lambda *_: None)
        assert not (root / "output" / "bad").exists()

    def test_a_bad_slug_raises_before_the_workspace_exists(self, root):
        """SEC-1. The order matters: validation is cheaper than creating a
        directory, and a refused run should leave nothing behind."""
        with pytest.raises(ValidationError):
            build_run(premise=PREMISE, config=resolve_config(profile="tiny", root=root),
                      slug="Bad Slug", root=root, report=lambda *_: None)
        assert list((root / "output").iterdir()) == []

    def test_a_bad_premise_raises(self, root):
        with pytest.raises(ValidationError):
            build_run(premise="tiny", config=resolve_config(profile="tiny", root=root),
                      slug="ok", root=root, report=lambda *_: None)

    def test_validation_can_be_skipped_for_a_resume(self, root):
        """A premise validated when the run started must stay resumable even if
        a rule is added later; re-checking would make old runs retroactively
        unresumable."""
        run = build_run(premise="tiny", config=resolve_config(profile="tiny", root=root),
                        slug="skip", root=root, report=lambda *_: None, validate=False)
        assert run.premise == "tiny"

    def test_a_contradictory_skill_stops_the_run_before_the_directory_exists(self, root):
        skill = root / ".claude" / "skills" / "publisher" / "SKILL.md"
        skill.write_text(
            skill.read_text(encoding="utf-8").replace(
                "writes_bible: false", "writes_bible: true"),
            encoding="utf-8")
        with pytest.raises(AgentError, match="Authority comes from the spec"):
            build_run(premise=PREMISE, config=resolve_config(profile="tiny", root=root),
                      slug="forged", root=root, report=lambda *_: None)
        assert not (root / "output" / "forged").exists()


class TestTheCliDoesNotWire:
    @pytest.mark.parametrize("constructor", [
        "Orchestrator(", "build_engine(", "load_agents(", "load_flow(",
    ])
    def test_the_cli_constructs_nothing(self, constructor):
        """If it did, the CLI path and the API path would drift, and only the
        one someone runs would keep working."""
        from novaforge import cli
        assert constructor not in inspect.getsource(cli)

    def test_the_cli_delegates_to_build_run(self):
        from novaforge import cli
        assert "build_run(" in inspect.getsource(cli)

    def test_the_package_docstring_points_here(self):
        """novaforge/__init__.py tells a reader where to start. A pointer at a
        module that does not exist is worse than no pointer."""
        import novaforge
        assert "composition" in novaforge.__doc__


class TestRedactor:
    def test_it_is_available_to_callers_that_print(self, monkeypatch):
        """SEC-2.2: the orchestrator can only scrub what it emits itself, and a
        caller printing a premise is printing something user-supplied."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-SECRETVALUE00001")
        assert "SECRETVALUE" not in redactor_for_output().scrub(
            "key is sk-ant-api03-SECRETVALUE00001")
