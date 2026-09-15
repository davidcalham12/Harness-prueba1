"""The Story Bible: the only shared state in the pipeline.

Two classes, deliberately:

* :class:`FileBible` can read *and* write, and is constructed once.
* :class:`ReadOnlyBible` wraps it and exposes only the reads.

The orchestrator hands :class:`FileBible` to the Worldbuilder and the Character
Architect, and :class:`ReadOnlyBible` to the other six agents - which therefore
have no ``write`` method to call (SEC-4.4, Interface Segregation). The runtime
role check in :func:`~novaforge.security.prompting.assert_may_write_bible` is a
second line of defence, not the only one.
"""

from __future__ import annotations

from typing import Callable, Mapping

from .security.prompting import assert_may_write_bible, scan_for_injection, wrap_untrusted
from .security.sandbox import Workspace
from .textops import Character, parse_characters, parse_world_rules

__all__ = ["SECTIONS", "FileBible", "ReadOnlyBible"]

SECTIONS = ("world", "characters", "timeline", "mysteries")

WriteHook = Callable[[str, str, int, list], None]


class FileBible:
    """Read/write access to ``bible/*.md`` inside the run workspace."""

    def __init__(self, workspace: Workspace, *, on_write: WriteHook | None = None) -> None:
        self._workspace = workspace
        self._on_write = on_write

    @staticmethod
    def path_for(section: str) -> str:
        if section not in SECTIONS:
            raise KeyError(f"unknown Bible section {section!r}; have {SECTIONS}")
        return f"bible/{section}.md"

    # -- reads -----------------------------------------------------------

    def exists(self, section: str) -> bool:
        return self._workspace.exists(self.path_for(section))

    def read(self, section: str) -> str:
        path = self.path_for(section)
        if not self._workspace.exists(path):
            return ""
        return self._workspace.read_text(path)

    def read_all(self) -> Mapping[str, str]:
        return {section: self.read(section) for section in SECTIONS}

    def is_complete(self) -> bool:
        return all(self.read(section).strip() for section in SECTIONS)

    def as_context(self, sections: tuple[str, ...] = SECTIONS) -> str:
        """The Bible as prompt context - always wrapped as untrusted (SEC-4.1).

        It is the source of truth for *facts*. It is never a source of
        instructions, and it was written by a model, so it is framed as data.
        """
        blocks = []
        for section in sections:
            text = self.read(section)
            if text.strip():
                blocks.append(wrap_untrusted(f"bible/{section}.md", text))
        return "\n\n".join(blocks)

    def characters(self) -> tuple[Character, ...]:
        return parse_characters(self.read("characters"))

    def world_rules(self) -> tuple[str, ...]:
        return parse_world_rules(self.read("world"))

    # -- the only write path ---------------------------------------------

    def write(self, section: str, content: str, *, role: str) -> str:
        """Write one Bible section. ``role`` is the role the orchestrator
        invoked - never anything the model said about itself (SEC-4.3)."""
        assert_may_write_bible(role)
        path = self.path_for(section)
        text = (content or "").strip() + "\n"
        self._workspace.write_text(path, content=text)
        if self._on_write is not None:
            self._on_write(role, section, len(text), scan_for_injection(text))
        return path


class ReadOnlyBible:
    """A reader with no ``write`` method. Handed to the six non-writing agents."""

    def __init__(self, bible: FileBible) -> None:
        self._bible = bible

    def exists(self, section: str) -> bool:
        return self._bible.exists(section)

    def read(self, section: str) -> str:
        return self._bible.read(section)

    def read_all(self) -> Mapping[str, str]:
        return self._bible.read_all()

    def is_complete(self) -> bool:
        return self._bible.is_complete()

    def as_context(self, sections: tuple[str, ...] = SECTIONS) -> str:
        return self._bible.as_context(sections)

    def characters(self) -> tuple[Character, ...]:
        return self._bible.characters()

    def world_rules(self) -> tuple[str, ...]:
        return self._bible.world_rules()
