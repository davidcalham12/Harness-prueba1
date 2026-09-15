"""The security layers, one module each. See `SECURITY.md` for why each exists.

All six ship: SEC-1 (`validation`), SEC-2 (`secrets`), SEC-3 (`sandbox`),
SEC-4 (`prompting`), SEC-5 (`escaping`) and SEC-6 (`audit`).

Two functions in SEC-5 - `xml_escape` and `svg_text` - are tested but not on
the shipping path, because CHG-001 removed the EPUB and the SVG cover. That is
stated in their docstrings rather than left to be discovered.
"""

from __future__ import annotations

from .escaping import (
    markdown_prose,
    pdf_string,
    safe_zip_name,
    strip_control,
    svg_text,
    xml_escape,
)
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
    "markdown_prose",
    "pdf_string",
    "safe_zip_name",
    "strip_control",
    "svg_text",
    "xml_escape",
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
