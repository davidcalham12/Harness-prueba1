"""The security layers, one module each. See `SECURITY.md` for why each exists.

Five of the six ship: SEC-1 (`validation`), SEC-2 (`secrets`), SEC-3
(`sandbox`), SEC-4 (`prompting`) and SEC-6 (`audit`). SEC-5 is named in
`SECURITY.md` and has no module yet - the escaping the shipping path needs
lives inside `export/markdown.py` and `export/pdf.py` instead, and its
absence is stated there and in `SECURITY.md` rather than silently bypassed.
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
from .secrets import KEY_ENV, MissingCredential, Redactor, load_api_key
from .validation import ValidationError, validate_premise, validate_slug

__all__ = [
    "BIBLE_WRITERS",
    "KEY_ENV",
    "MissingCredential",
    "Redactor",
    "ValidationError",
    "load_api_key",
    "validate_premise",
    "validate_slug",
    "BibleWriteDenied",
    "SandboxViolation",
    "UNTRUSTED_CLAUSE",
    "Workspace",
    "assert_may_write_bible",
    "may_write_bible",
    "scan_for_injection",
    "wrap_untrusted",
]
