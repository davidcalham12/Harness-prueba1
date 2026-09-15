"""SEC-3 - the filesystem sandbox.

No module in NovaForge joins path strings and calls ``open()``. Every read and
write goes through a :class:`Workspace` rooted at ``output/<slug>/``, because
chapter filenames, slugs and artefact names all originate outside the program.

Two properties worth stating exactly:

* **Containment is checked after ``realpath``.** A symlink planted inside the
  run directory that points somewhere else is caught, which a purely textual
  ``..`` check would miss.
* **Writes are atomic.** Temp file in the same directory, then ``os.replace``.
  A crash mid-run cannot leave a half-written Bible or a truncated
  ``state.json`` that the next resume would read as authoritative.

**Not covered:** an attacker who can already write to the output directory.
This bounds *this program's* writes.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

__all__ = ["SandboxViolation", "Workspace"]

# Reserved on Windows in every directory, with or without an extension.
_WINDOWS_DEVICES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


class SandboxViolation(ValueError):
    """A path escaped the workspace, or was not a shape we accept."""


class Workspace:
    """Bounded read/write access to one run directory."""

    def __init__(self, root: str | os.PathLike[str], *, create: bool = True) -> None:
        root_path = Path(root)
        if create:
            root_path.mkdir(parents=True, exist_ok=True)
        if not root_path.exists():
            raise SandboxViolation(f"workspace root does not exist: {root_path}")
        # realpath once, at construction: every later check compares against
        # the resolved root, so a symlinked root is handled consistently.
        self._root = Path(os.path.realpath(root_path))

    @property
    def root(self) -> Path:
        return self._root

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"Workspace({str(self._root)!r})"

    # -- path resolution -------------------------------------------------

    def _check_parts(self, relative: str) -> tuple[str, ...]:
        text = str(relative or "").strip().replace("\\", "/")
        if not text:
            raise SandboxViolation("empty path")
        if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
            raise SandboxViolation(f"absolute path refused: {relative!r}")
        parts = tuple(p for p in text.split("/") if p not in ("", "."))
        if not parts:
            raise SandboxViolation(f"path resolves to nothing: {relative!r}")
        for part in parts:
            if part == "..":
                raise SandboxViolation(f"parent traversal refused: {relative!r}")
            if part.split(".")[0].lower() in _WINDOWS_DEVICES:
                raise SandboxViolation(f"reserved device name: {part!r}")
            if any(ch in part for ch in '<>:"|?*\0'):
                raise SandboxViolation(f"illegal character in path: {part!r}")
        return parts

    def resolve(self, relative: str, *, must_exist: bool = False) -> Path:
        """Absolute path for ``relative``, proven to be inside the workspace."""
        parts = self._check_parts(relative)
        candidate = self._root.joinpath(*parts)
        if must_exist and not candidate.exists():
            raise FileNotFoundError(f"{relative} not found in {self._root}")
        # Resolve the deepest existing ancestor: a path that does not exist yet
        # still has to land inside the root once it does.
        probe = candidate
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        real = Path(os.path.realpath(probe))
        if real != self._root and self._root not in real.parents:
            raise SandboxViolation(
                f"{relative!r} resolves to {real}, outside {self._root} (SEC-3.2)"
            )
        return candidate

    # -- reads -----------------------------------------------------------

    def exists(self, relative: str) -> bool:
        try:
            return self.resolve(relative).exists()
        except SandboxViolation:
            return False

    def read_text(self, relative: str) -> str:
        return self.resolve(relative, must_exist=True).read_text(encoding="utf-8")

    def read_json(self, relative: str) -> Any:
        return json.loads(self.read_text(relative))

    def glob(self, pattern: str) -> list[str]:
        """Workspace-relative paths matching ``pattern``, sorted.

        Sorted because chapter order must not depend on directory order - a run
        that publishes chapters in filesystem order is a run that publishes
        them differently on another machine.
        """
        return sorted(
            str(p.relative_to(self._root)).replace("\\", "/")
            for p in self._root.glob(pattern)
            if p.is_file()
        )

    # -- writes ----------------------------------------------------------

    def write_text(self, relative: str, *, content: str) -> Path:
        """Atomically write ``content``. Parents are created as needed."""
        target = self.resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=".novaforge-", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            # Leaving a .tmp behind would make the next run's glob lie.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return target

    def write_bytes(self, relative: str, *, data: bytes) -> Path:
        """Atomically write binary content. Same containment, same rename.

        A PDF written non-atomically is a PDF that a crash leaves unopenable,
        and the xref table at the end is exactly the part that would be lost.
        """
        target = self.resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=".novaforge-", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return target

    def read_bytes(self, relative: str) -> bytes:
        return self.resolve(relative, must_exist=True).read_bytes()

    def write_json(self, relative: str, *, data: Any) -> Path:
        """Write JSON with sorted keys, so a diff between two runs is a diff of
        the content and not of the key order."""
        text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
        return self.write_text(relative, content=text + "\n")

    def append_line(self, relative: str, *, line: str) -> Path:
        """Append one line. Used by the append-only audit log (SEC-6.2)."""
        target = self.resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line.rstrip("\n") + "\n")
        return target

    def read_lines(self, relative: str) -> Iterable[str]:
        if not self.exists(relative):
            return []
        return [ln for ln in self.read_text(relative).splitlines() if ln.strip()]
