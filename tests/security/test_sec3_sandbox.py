"""SEC-3 - the filesystem sandbox.

Chapter filenames, slugs and artefact names all originate outside the program,
so the property under test is that *no* string can be talked into a write
outside ``output/<slug>/``.

The symlink test is the one that earns its keep: a purely textual ``..`` check
passes it and is still wrong.
"""

from __future__ import annotations

import json
import os

import pytest

from novaforge.security.sandbox import SandboxViolation, Workspace


class TestContainment:
    @pytest.mark.parametrize("path", [
        "../escape.md", "..\\escape.md", "a/../../b", "a/b/../../../c",
        "/etc/passwd", "C:/Windows/system32/x.txt", "", "   ", ".",
    ])
    def test_refuses_to_leave_the_workspace(self, workspace, path):
        with pytest.raises(SandboxViolation):
            workspace.write_text(path, content="x")

    @pytest.mark.parametrize("name", ["con", "NUL.txt", "lpt1/x.md", "aux", "COM3.md"])
    def test_refuses_windows_device_names(self, workspace, name):
        """Reserved in every directory, with or without an extension."""
        with pytest.raises(SandboxViolation):
            workspace.write_text(name, content="x")

    @pytest.mark.parametrize("name", ['a<b.md', 'a>b.md', 'a|b.md', 'a?b.md', 'a*b.md'])
    def test_refuses_illegal_characters(self, workspace, name):
        with pytest.raises(SandboxViolation):
            workspace.write_text(name, content="x")

    def test_a_symlink_pointing_outside_is_caught(self, tmp_path):
        """SEC-3.2: containment is checked after realpath, which a textual
        '..' check would miss entirely."""
        outside = tmp_path / "outside"
        outside.mkdir()
        space = Workspace(tmp_path / "run")
        try:
            os.symlink(outside, space.root / "link", target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("this platform/user cannot create symlinks")
        with pytest.raises(SandboxViolation):
            space.write_text("link/escaped.md", content="x")

    def test_exists_returns_false_for_a_bad_path_rather_than_raising(self, workspace):
        assert workspace.exists("../nope") is False

    def test_legal_nested_paths_are_allowed(self, workspace):
        workspace.write_text("critiques/ch01.continuity.json", content="{}")
        assert workspace.exists("critiques/ch01.continuity.json")


class TestWrites:
    def test_round_trip(self, workspace):
        workspace.write_text("bible/world.md", content="hola\n")
        assert workspace.read_text("bible/world.md") == "hola\n"

    def test_parents_are_created(self, workspace):
        workspace.write_text("a/b/c/d.md", content="x")
        assert (workspace.root / "a" / "b" / "c" / "d.md").exists()

    def test_writes_leave_no_temp_files_behind(self, workspace):
        """A stray .tmp would make the next run's glob lie."""
        workspace.write_text("bible/world.md", content="x")
        assert not [p for p in (workspace.root / "bible").iterdir()
                    if p.name.startswith(".novaforge-")]

    def test_a_failed_write_does_not_truncate_the_previous_file(self, workspace):
        """Atomic: a crash cannot leave a half-written state.json that the next
        resume would read as authoritative."""
        workspace.write_text("state.json", content='{"good": true}')
        with pytest.raises(TypeError):
            workspace.write_text("state.json", content=None)  # type: ignore[arg-type]
        assert json.loads(workspace.read_text("state.json")) == {"good": True}

    def test_json_is_written_with_sorted_keys(self, workspace):
        """So a diff between two runs is a diff of content, not of key order."""
        workspace.write_json("s.json", data={"b": 2, "a": 1})
        text = workspace.read_text("s.json")
        assert text.index('"a"') < text.index('"b"')

    def test_append_line_is_append_only(self, workspace):
        for row in ("one", "two", "three"):
            workspace.append_line("logs/agents.jsonl", line=row)
        assert list(workspace.read_lines("logs/agents.jsonl")) == ["one", "two", "three"]

    def test_reading_a_missing_log_yields_nothing(self, workspace):
        assert list(workspace.read_lines("logs/absent.jsonl")) == []


class TestGlob:
    def test_results_are_sorted_not_filesystem_ordered(self, workspace):
        """A run that publishes chapters in directory order publishes them
        differently on another machine."""
        for name in ("ch03", "ch01", "ch02"):
            workspace.write_text(f"chapters/{name}.md", content="x")
        assert workspace.glob("chapters/*.md") == [
            "chapters/ch01.md", "chapters/ch02.md", "chapters/ch03.md"]

    def test_paths_come_back_workspace_relative_with_forward_slashes(self, workspace):
        workspace.write_text("chapters/ch01.md", content="x")
        assert workspace.glob("chapters/*.md") == ["chapters/ch01.md"]

    def test_directories_are_not_returned(self, workspace):
        workspace.write_text("a/b.md", content="x")
        assert workspace.glob("*") == []


class TestConstruction:
    def test_a_missing_root_is_created_by_default(self, tmp_path):
        assert Workspace(tmp_path / "new").root.exists()

    def test_create_false_refuses_a_missing_root(self, tmp_path):
        with pytest.raises(SandboxViolation):
            Workspace(tmp_path / "absent", create=False)
