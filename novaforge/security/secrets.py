"""SEC-2 - the credential, and keeping it out of everything the run writes.

**The key is read from the environment only.** There is no ``--api-key`` flag,
and adding one would be a mistake rather than a convenience: a flag lands in
shell history, and on most systems it lands in the process table where any
other local user can read it with ``ps``.

**Everything the run writes goes through the redactor.** Logs, ``state.json``
and the terminal output all get copied into tickets and chat messages, usually
by someone in a hurry who is quoting a traceback. The redactor scrubs
key-shaped strings, bearer tokens and ``api_key=`` assignments — and, when a
key is actually loaded, that exact string as a literal, which is the case the
pattern-matching would otherwise miss for a provider whose keys look nothing
like Anthropic's.

**Not covered:** what the API provider does with the prompts you send. Read
their retention policy.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

__all__ = ["KEY_ENV", "MissingCredential", "Redactor", "load_api_key"]

KEY_ENV = "ANTHROPIC_API_KEY"
PLACEHOLDER = "[REDACTED]"

# Ordered most specific first, so `api_key=sk-ant-...` is reported as an
# assignment rather than twice.
#
# The assignment pattern keeps the key name and the separator in group 1 and
# only replaces group 2, so a scrubbed log still says *that* a credential was
# configured — which an operator reading the log needs to know — without saying
# what it was. The optional quotes on both sides are what make it work on JSON
# (`"token": "value"`) as well as on `token=value`; without them the value group
# stops at the opening quote and the secret survives.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("assignment", re.compile(
        r"(?i)(\b(?:api[_-]?key|secret|token|password|passwd|auth)\b"
        r"[\"']?\s*[:=]\s*[\"']?)"
        r"([^\s,;\"'}\)]{6,})")),
    ("bearer", re.compile(r"(?i)\b(bearer|basic)\s+([A-Za-z0-9._~+/=-]{12,})")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}")),
    # Hyphens and underscores matter: a real project key is `sk-proj-...`, and a
    # pattern of `[A-Za-z0-9]` alone stops dead at the first hyphen.
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{18,}")),
    ("aws-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
)


class MissingCredential(RuntimeError):
    """No API key in the environment, and a paid engine was asked for."""


def load_api_key(env: Mapping[str, str] | None = None) -> str:
    """Read the credential from the environment. Never from a flag or a file.

    Raises with instructions rather than returning ``None``, because a caller
    that treats a missing key as "run without one" produces a confusing failure
    much later, inside the HTTP layer.
    """
    source = os.environ if env is None else env
    key = (source.get(KEY_ENV) or "").strip()
    if not key:
        raise MissingCredential(
            f"{KEY_ENV} is not set. The credential is read from the environment "
            f"only - there is no --api-key flag, because a flag lands in shell "
            f"history and in the process table (SEC-2.1).\n"
            f"  bash:       export {KEY_ENV}=sk-ant-...\n"
            f"  PowerShell: $env:{KEY_ENV} = 'sk-ant-...'"
        )
    return key


@dataclass
class Redactor:
    """Scrubs secrets from anything on its way out of the program.

    ``literals`` are exact strings — the live key, typically. They are matched
    before the patterns, because an exact match is certain where a pattern is a
    guess, and because a key from a provider this module has never heard of
    would otherwise slip through.
    """

    literals: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Redactor":
        """A redactor that knows the live key, if there is one.

        Works with no key set, which matters: the mock engine needs no
        credential, and the redactor is on the logging path either way.
        """
        source = os.environ if env is None else env
        literals = []
        for name in (KEY_ENV, "NOVAFORGE_AUDIT_KEY"):
            value = (source.get(name) or "").strip()
            # Very short values are not credentials worth matching, and
            # redacting a two-character string would gut ordinary prose.
            if len(value) >= 8:
                literals.append(value)
        return cls(literals=tuple(literals))

    def with_literal(self, value: str) -> "Redactor":
        if not value or len(value) < 8 or value in self.literals:
            return self
        return Redactor(literals=self.literals + (value,))

    # -- the one operation ------------------------------------------------

    def scrub(self, text: str) -> str:
        """Return ``text`` with every secret replaced by ``[REDACTED]``."""
        if not text:
            return text
        out = text
        for literal in self.literals:
            out = out.replace(literal, PLACEHOLDER)
        out = _PATTERNS[0][1].sub(lambda m: f"{m.group(1)}{PLACEHOLDER}", out)
        out = _PATTERNS[1][1].sub(lambda m: f"{m.group(1)} {PLACEHOLDER}", out)
        for _name, pattern in _PATTERNS[2:]:
            out = pattern.sub(PLACEHOLDER, out)
        return out

    def scrub_data(self, data: Any) -> Any:
        """Scrub recursively through dicts, lists and strings.

        ``state.json`` and every audit row are nested structures, so scrubbing
        only the top-level string would be scrubbing almost nothing.
        """
        if isinstance(data, str):
            return self.scrub(data)
        if isinstance(data, Mapping):
            return {k: self.scrub_data(v) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            kind = type(data)
            return kind(self.scrub_data(v) for v in data)
        return data

    def finds_secret(self, text: str) -> bool:
        """True if scrubbing would change ``text``. Used by tests, not by the
        shipping path - the shipping path always scrubs."""
        return self.scrub(text) != text

    def __call__(self, text: str) -> str:
        return self.scrub(text)
