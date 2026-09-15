"""The security layers, one module each. See `SECURITY.md` for why each exists.

Slice 1 ships SEC-3 (`sandbox`) and SEC-4 (`prompting`), because they are the
two the pipeline cannot run without: every write goes through the Workspace,
and every piece of model-written text reaches another agent through
``wrap_untrusted``. SEC-1, SEC-2, SEC-5 and SEC-6 are named in `SECURITY.md`
and not yet implemented; nothing imports them, so their absence is visible
rather than silently bypassed.
"""

from __future__ import annotations

from .prompting import (
    BIBLE_WRITERS,
    UNTRUSTED_CLAUSE,
    BibleWriteDenied,
    assert_may_write_bible,
    may_write_bible,
    scan_for_injection,
    wrap_untrusted,
)
from .sandbox import SandboxViolation, Workspace

__all__ = [
    "BIBLE_WRITERS",
    "BibleWriteDenied",
    "SandboxViolation",
    "UNTRUSTED_CLAUSE",
    "Workspace",
    "assert_may_write_bible",
    "may_write_bible",
    "scan_for_injection",
    "wrap_untrusted",
]
