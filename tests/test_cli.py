"""The command line.

The `--force` tests exist because of a real bug: ``logs/agents.jsonl`` is
append-only, so a second ``new`` into an occupied slug produced a log claiming
48 calls for a 16-call run. An audit log that describes three runs as one
cannot be used to reconstruct any of them.
"""

from __future__ import annotations

import json

import pytest

from conftest import isolated_root
from novaforge import cli
from novaforge.orchestrator import generated_paths, reset_run
from novaforge.security.sandbox import Workspace

PREMISE = "A deep-space salvage crew finds a derelict that remembers them"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """A throwaway repo root, so a CLI test never writes into ``output/``."""
    root = isolated_root(tmp_path)
    monkeypatch.setattr(cli, "package_root", lambda: root)
    return root


class TestNew:
    def test_a_run_succeeds_and_reports_zero(self, isolated):
        assert cli.main(["new", PREMISE, "--profile", "tiny", "--slug", "a",
                         "--engine", "mock", "--quiet"]) == 0
        assert (isolated / "output" / "a" / "dist" / "book.md").exists()

    def test_flags_override_the_profile(self, isolated):
        """CFG-4 — every flag is a config key. --chapters 2 and editing
        novel.chapters are the same change by different routes."""
        cli.main(["new", PREMISE, "--profile", "tiny", "--slug", "b", "--engine", "mock",
                  "--chapters", "2", "--quiet"])
        state = json.loads((isolated / "output" / "b" / "state.json").read_text("utf-8"))
        assert len(state["chapters"]) == 2

    def test_the_slug_is_derived_from_the_premise_when_absent(self, isolated):
        cli.main(["new", PREMISE, "--profile", "tiny", "--engine", "mock", "--quiet"])
        assert (isolated / "output" /
                "a-deep-space-salvage-crew-finds-a-derelict-that").exists()

    def test_an_unknown_profile_is_refused(self, isolated, capsys):
        assert cli.main(["new", PREMISE, "--profile", "enormous", "--quiet"]) == 2
        assert "enormous" in capsys.readouterr().err

    def test_an_unknown_engine_is_refused(self, isolated, capsys):
        assert cli.main(["new", PREMISE, "--profile", "tiny", "--engine", "mokc",
                         "--quiet"]) == 2
        assert "unknown engine" in capsys.readouterr().err

    def test_the_anthropic_engine_fails_with_a_message_not_a_traceback(self, isolated,
                                                                      capsys):
        assert cli.main(["new", PREMISE, "--profile", "tiny", "--engine", "anthropic",
                         "--quiet"]) == 2
        assert "not implemented" in capsys.readouterr().err


class TestForce:
    def test_a_second_new_into_an_occupied_slug_is_refused(self, isolated, capsys):
        cli.main(["new", PREMISE, "--profile", "tiny", "--slug", "c",
                  "--engine", "mock", "--quiet"])
        assert cli.main(["new", PREMISE, "--profile", "tiny", "--slug", "c",
                         "--engine", "mock", "--quiet"]) == 1
        message = capsys.readouterr().err
        assert "already exists" in message
        assert "resume c" in message and "--force" in message

    def test_force_replaces_the_run_and_the_log_describes_one_run(self, isolated):
        """CFG-7 — regenerating over an existing run is a deliberate act,
        because the audit log is append-only."""
        for _ in range(2):
            cli.main(["new", PREMISE, "--profile", "tiny", "--slug", "d",
                      "--engine", "mock", "--force", "--quiet"])
        root = isolated / "output" / "d"
        state = json.loads((root / "state.json").read_text("utf-8"))
        rows = [json.loads(l) for l in
                (root / "logs" / "agents.jsonl").read_text("utf-8").splitlines() if l.strip()]
        assert sum(1 for r in rows if r["event"] == "call") == state["calls"]

    def test_force_does_not_delete_files_the_run_did_not_generate(self, isolated):
        cli.main(["new", PREMISE, "--profile", "tiny", "--slug", "e",
                  "--engine", "mock", "--quiet"])
        keeper = isolated / "output" / "e" / "README.md"
        keeper.write_text("hand-written, not generated", encoding="utf-8")
        cli.main(["new", PREMISE, "--profile", "tiny", "--slug", "e",
                  "--engine", "mock", "--force", "--quiet"])
        assert keeper.read_text(encoding="utf-8") == "hand-written, not generated"

    def test_a_shorter_rerun_does_not_publish_the_longer_run_s_chapters(self, isolated):
        """Without the reset, publish would glob leftover finals and ship a
        book with chapters the current config never asked for."""
        cli.main(["new", PREMISE, "--profile", "tiny", "--slug", "f", "--engine", "mock",
                  "--chapters", "6", "--quiet"])
        cli.main(["new", PREMISE, "--profile", "tiny", "--slug", "f", "--engine", "mock",
                  "--chapters", "2", "--force", "--quiet"])
        book = (isolated / "output" / "f" / "dist" / "book.md").read_text("utf-8")
        assert "Chapter 2" in book
        assert "Chapter 3" not in book


class TestReset:
    def test_generated_paths_are_derived_from_the_spec(self, flow):
        paths = generated_paths(flow)
        for expected in ("bible", "chapters", "critiques", "dist", "outline.md",
                         "logs", "state.json", "config.snapshot.json"):
            assert expected in paths

    def test_reset_removes_only_what_exists(self, tmp_path, flow):
        space = Workspace(tmp_path / "r")
        space.write_text("bible/world.md", content="x")
        space.write_text("keep.txt", content="keep")
        removed = reset_run(space, flow)
        assert "bible" in removed
        assert "dist" not in removed
        assert space.exists("keep.txt")


class TestResumeCommand:
    def test_resume_without_a_run_is_refused(self, isolated, capsys):
        assert cli.main(["resume", "nope", "--quiet"]) == 1
        message = capsys.readouterr().err
        assert "nothing to resume" in message
        assert "nope" in message  # names the slug it looked for

    def test_resume_does_not_need_the_profile_repeated(self, isolated):
        cli.main(["new", PREMISE, "--profile", "tiny", "--slug", "g",
                  "--engine", "mock", "--quiet"])
        assert cli.main(["resume", "g", "--quiet"]) == 0
        state = json.loads((isolated / "output" / "g" / "state.json").read_text("utf-8"))
        assert len(state["chapters"]) == 3


class TestStatus:
    def test_status_reports_a_finished_run(self, isolated, capsys):
        cli.main(["new", PREMISE, "--profile", "tiny", "--slug", "h",
                  "--engine", "mock", "--quiet"])
        assert cli.main(["status", "h"]) == 0
        out = capsys.readouterr().out
        assert "complete" in out
        assert "ch01" in out and "ch03" in out

    def test_status_on_a_missing_run_is_refused(self, isolated, capsys):
        assert cli.main(["status", "absent"]) == 1
        assert "no run" in capsys.readouterr().err

    def test_status_does_not_modify_the_run(self, isolated):
        cli.main(["new", PREMISE, "--profile", "tiny", "--slug", "i",
                  "--engine", "mock", "--quiet"])
        path = isolated / "output" / "i" / "state.json"
        before = path.read_bytes()
        cli.main(["status", "i"])
        assert path.read_bytes() == before
