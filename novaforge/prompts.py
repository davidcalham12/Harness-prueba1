"""Where an agent's prompt comes from.

The project began with prompts in ``.claude/skills/<agent>/SKILL.md``, versioned
next to the spec they implement. They have moved to Langfuse Prompt Management,
and this module is the seam.

**The SKILL.md files have not gone away, and should not.** They are the
fallback Langfuse itself asks for: :meth:`Langfuse.get_prompt` takes a
``fallback`` precisely because a prompt service being unreachable should not
stop the thing it serves. So the arrangement is:

* **Langfuse is the source of truth.** Editing a prompt there changes the next
  run, with a version history and a label — which is the whole reason for
  moving, and something a file in a repository cannot give you without a
  commit and a deploy.
* **SKILL.md is the fallback, and the seed.** ``tools/push_prompts.py`` uploads
  them; a run with no network or no credentials uses them unchanged.
* **`tools/check_specs.py` still reads the files.** The 40 traced requirements
  and the front-matter-versus-spec check are file-based, and moving the prompts
  did not move the thing those checks are about: a skill's declared role, model
  and ``writes_bible`` remain a repository fact, cross-checked against
  ``specs/flow.yaml`` and against the code (SEC-4.3).

That last point is the one worth being careful about. **Authority is never read
from Langfuse.** Whether an agent may write the Story Bible is decided by the
flow spec and the code; a prompt fetched from a remote service supplies wording
and nothing else. A service that could grant Bible access by editing a prompt
would make SEC-4.3 a suggestion.
"""

from __future__ import annotations

import os
from typing import Any, Callable

__all__ = ["FilePrompts", "LangfusePrompts", "PromptSource", "build_prompt_source",
           "langfuse_host"]

# Langfuse's own documentation says LANGFUSE_BASE_URL; older material and
# the SDK's own parameter say host. Reading only one of them means anyone
# following the current docs sets a variable nothing reads, their region
# silently defaults to the EU, and the failure that follows is an auth
# error that says nothing about regions. Both are accepted.
HOST_ENV = ("LANGFUSE_BASE_URL", "LANGFUSE_HOST")


def langfuse_host() -> str | None:
    """The configured host, from either environment variable."""
    for name in HOST_ENV:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


class FilePrompts:
    """The prompt written in the agent's own ``SKILL.md``.

    The original arrangement, still the fallback, and still what runs when
    nothing else is configured.
    """

    name = "file"

    def get(self, agent_name: str, default: str) -> str:
        return default

    def describe(self, agent_name: str) -> str:
        return f".claude/skills/{agent_name}/SKILL.md"


class LangfusePrompts:
    """Prompts from Langfuse Prompt Management, falling back to the file.

    Cached by the SDK for ``cache_ttl_seconds``, so a run does not make one
    prompt request per call. A run that starts while Langfuse is down uses the
    fallback and says so, rather than failing — the prompts are the same text
    either way, and stopping a novel because a dashboard is unreachable would
    be the wrong trade.
    """

    name = "langfuse"

    def __init__(self, *, label: str = "production", cache_ttl_seconds: int = 300,
                 report: Callable[[str], None] | None = None, **_: Any) -> None:
        from langfuse import Langfuse  # raises if the extra is not installed

        self._report = report or (lambda _: None)
        public, secret = (os.environ.get("LANGFUSE_PUBLIC_KEY"),
                          os.environ.get("LANGFUSE_SECRET_KEY"))
        self._client = None
        if public and secret:
            self._client = Langfuse(public_key=public, secret_key=secret,
                                    host=langfuse_host())
        else:
            # No credentials is the same condition as an unreachable service,
            # and was not treated as one: an earlier version raised here while
            # `get` fell back, so the same problem killed a run or did not
            # depending on when it happened. Both now fall back and say so.
            self._report(
                "  prompts: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are not "
                "set; every prompt comes from its SKILL.md. The wording is the "
                "same text either way (SEC-2.1)."
            )
        self._label = label
        self._ttl = cache_ttl_seconds
        self._fell_back: set[str] = set()

    def get(self, agent_name: str, default: str) -> str:
        """The prompt for ``agent_name``, or ``default`` if it cannot be had.

        Falling back is reported once per agent rather than per call: a run of
        thirty-four chapters would otherwise print the same line a hundred
        times, and the operator needs to know it happened, not how often.
        """
        if self._client is None:
            return default
        try:
            prompt = self._client.get_prompt(
                f"novaforge/{agent_name}",
                label=self._label,
                cache_ttl_seconds=self._ttl,
                fallback=default,
            )
            text = prompt.get_langchain_prompt() if hasattr(prompt, "get_langchain_prompt") \
                else getattr(prompt, "prompt", default)
            if isinstance(text, str) and text.strip():
                return text
        except Exception as exc:  # noqa: BLE001 - a prompt service is not a dependency
            if agent_name not in self._fell_back:
                self._fell_back.add(agent_name)
                self._report(
                    f"  prompts: {agent_name} came from its SKILL.md "
                    f"({type(exc).__name__}); Langfuse was not reachable"
                )
        return default

    def describe(self, agent_name: str) -> str:
        if self._client is None:
            return f".claude/skills/{agent_name}/SKILL.md (no credentials)"
        return f"langfuse:novaforge/{agent_name}@{self._label}"


class PromptSource:
    """Structural type: ``get(name, default)`` and ``describe(name)``."""


def build_prompt_source(name: str | None = None, **options) -> Any:
    """The source named in ``agents.prompt_source``."""
    key = (name or "file").strip().lower()
    if key in ("", "file", "skill", "local"):
        return FilePrompts()
    if key == "langfuse":
        return LangfusePrompts(**options)
    raise ValueError(
        f"unknown prompt source {name!r}; have 'file' and 'langfuse'"
    )
