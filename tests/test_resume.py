"""Resuming an interrupted run.

RUNBOOK §5 describes the repair by hand: delete ``chapters/ch03.md`` and
``ch03.final.md``, set that chapter's status back to ``pending``, drop FLOW-4,
FLOW-5 and FLOW-6 from ``completed_stages``, and run again - *only chapter 3 is
rewritten*. This module does exactly that, automatically.

The cost assertion is the one that matters. Resume that re-ran every chapter
would still produce a correct book, so correctness alone cannot tell you the
feature works; only the call count can.
"""

from __future__ import annotations

import json

import pytest

from conftest import run_novel


def break_chapter_three(space):
    """The RUNBOOK §5 repair, applied to a completed run."""
    (space.root / "chapters" / "ch03.md").unlink()
    (space.root / "chapters" / "ch03.final.md").unlink()
    state = space.read_json("state.json")
    for chapter in state["chapters"]:
        if chapter["number"] == 3:
            chapter["status"] = "pending"
    state["completed_stages"] = [s for s in state["completed_stages"]
                                 if s not in ("FLOW-4", "FLOW-5", "FLOW-6")]
    space.write_json("state.json", data=state)
    return state


@pytest.fixture
def interrupted(tmp_path):
    _, state, space = run_novel(tmp_path, slug="r")
    before = state.calls
    break_chapter_three(space)
    return space, before


class TestResumeRewritesOnlyWhatIsMissing:
    def test_only_chapter_three_is_rewritten(self, tmp_path, interrupted):
        space, _ = interrupted
        lines: list[str] = []
        _, state, _ = run_novel(tmp_path, slug="r", resume=True, report=lines.append)
        report = "\n".join(lines)
        assert "ch01 already approved, reused" in report
        assert "ch02 already approved, reused" in report
        assert "ch03 draft 1" in report
        assert state.stage == "complete"

    def test_the_reused_chapters_cost_no_calls(self, tmp_path, interrupted):
        """Resume that re-ran everything would still produce a correct book.
        Only the call count distinguishes the two."""
        space, before = interrupted
        _, state, _ = run_novel(tmp_path, slug="r", resume=True)
        added = state.calls - before
        # one chapter draft + its summary + three style passes + one synopsis
        assert added == 6

    def test_the_completed_stages_that_were_kept_are_skipped(self, tmp_path, interrupted):
        space, _ = interrupted
        lines: list[str] = []
        run_novel(tmp_path, slug="r", resume=True, report=lines.append)
        report = "\n".join(lines)
        for stage in ("FLOW-1", "FLOW-2", "FLOW-3"):
            assert f"{stage}" in report and "already done, skipped" in report

    def test_the_book_is_rebuilt_complete(self, tmp_path, interrupted):
        space, _ = interrupted
        run_novel(tmp_path, slug="r", resume=True)
        book = space.read_text("dist/book.md")
        for number in (1, 2, 3):
            assert f"Chapter {number}" in book


class TestResumeOnACompletedRun:
    def test_it_reports_everything_done_and_exits_cleanly(self, tmp_path):
        _, state, _ = run_novel(tmp_path, slug="done")
        lines: list[str] = []
        _, resumed, _ = run_novel(tmp_path, slug="done", resume=True, report=lines.append)
        assert resumed.stage == "complete"
        assert resumed.calls == state.calls  # nothing re-run, nothing re-billed
        assert all("already done, skipped" in l for l in lines if "FLOW-" in l)

    def test_notes_do_not_accumulate_across_resumes(self, tmp_path):
        """The same fact arriving twice is one fact."""
        run_novel(tmp_path, slug="notes")
        _, state, _ = run_novel(tmp_path, slug="notes", resume=True)
        assert len(state.notes) == len(set(state.notes))


class TestResumeRefusesToChangeTheNovel:
    def test_a_different_config_is_refused(self, tmp_path):
        """A resumed run must be the same novel, or 'resume' would silently
        mean 'start a different book in the same directory'."""
        from novaforge.orchestrator import StageFailed
        run_novel(tmp_path, slug="mismatch")
        with pytest.raises(StageFailed, match="cannot resume"):
            run_novel(tmp_path, slug="mismatch", resume=True,
                      overrides={"novel": {"chapters": 5}})

    def test_disk_wins_when_state_and_disk_disagree(self, tmp_path):
        """state.json says a chapter is done, the file is gone: rewrite it
        rather than publishing a book with a hole in it."""
        _, _, space = run_novel(tmp_path, slug="lost")
        (space.root / "chapters" / "ch02.md").unlink()
        state = space.read_json("state.json")
        state["completed_stages"] = [s for s in state["completed_stages"]
                                     if s not in ("FLOW-4", "FLOW-5", "FLOW-6")]
        space.write_json("state.json", data=state)
        lines: list[str] = []
        _, resumed, _ = run_novel(tmp_path, slug="lost", resume=True, report=lines.append)
        assert "ch02 draft 1" in "\n".join(lines)
        assert resumed.stage == "complete"


class TestCliResume:
    def test_resume_recovers_the_config_without_repeating_the_profile(self, tmp_path,
                                                                     monkeypatch):
        """Forgetting `--profile tiny` must not silently continue a
        three-chapter book as a twelve-chapter one."""
        from novaforge import cli
        from novaforge.config import package_root

        monkeypatch.setattr(cli, "package_root", lambda: package_root())
        _, _, space = run_novel(package_root() / "output", slug="_cli_resume_test")
        try:
            assert cli.main(["resume", "_cli_resume_test", "--quiet"]) == 0
            assert space.read_json("state.json")["chapters"].__len__() == 3
        finally:
            import shutil
            shutil.rmtree(space.root, ignore_errors=True)
