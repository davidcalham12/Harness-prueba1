"""SEC-1 - input validation.

**Rejects rather than coerces.** A slug that is quietly cleaned up is a slug
whose final value the caller never saw, and the run directory it names is one
they did not choose. Every function here either returns its input unchanged or
raises.

The slug matters more than it looks: it is the only path component in the whole
program that comes from a human, and everything under ``output/<slug>/`` is
built from it. :mod:`novaforge.security.sandbox` is the second line of defence;
this is the first, and the two check different things — the sandbox asks "does
this resolve inside the workspace?", this asks "is this a name we accept at
all?".

**Not covered: the *content* of a premise.** NovaForge does not moderate what
you ask it to write. What it does refuse is a premise carrying control or
invisible-format characters — the class of character that hides text from a
human reviewer while the model still reads it.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "MAX_PREMISE_CHARS",
    "MIN_PREMISE_CHARS",
    "SLUG_PATTERN",
    "ValidationError",
    "validate_premise",
    "validate_slug",
]

# SEC-1.1. Lowercase, digits and hyphens; must start with an alphanumeric.
# 64 characters is the ceiling because the slug becomes a directory name that
# other paths are built under, and Windows still has a 260-character default.
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

MIN_PREMISE_CHARS = 8
MAX_PREMISE_CHARS = 2000

_WINDOWS_DEVICES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


class ValidationError(ValueError):
    """Input was refused. The message says what was wrong and what is accepted."""


def _invisible_characters(text: str) -> list[tuple[int, str, str]]:
    """Unicode ``Cc``/``Cf`` characters, with their positions.

    ``Cf`` is the interesting class: zero-width joiners, bidirectional
    overrides, soft hyphens. They are invisible to a reviewer reading a premise
    and fully visible to the model reading it, which is a gap worth refusing
    rather than narrowing.
    """
    found = []
    for index, char in enumerate(text):
        if char in "\t\n\r":
            continue
        category = unicodedata.category(char)
        if category in ("Cc", "Cf"):
            found.append((index, char, category))
    return found


def validate_slug(slug: str) -> str:
    """Return ``slug`` unchanged, or raise.

    Deliberately not a sanitiser. ``slugify`` in :mod:`novaforge.textops`
    produces a *candidate*; this authorises it. Keeping the two apart means
    nothing can accidentally both clean up and approve a name in one step.
    """
    if not isinstance(slug, str):
        raise ValidationError(f"slug must be a string, got {type(slug).__name__}")
    if not slug:
        raise ValidationError("slug is empty")
    if slug != slug.strip():
        raise ValidationError(
            f"slug {slug!r} has leading or trailing whitespace; "
            f"refused rather than trimmed, so the directory you get is the "
            f"one you asked for"
        )
    if not SLUG_PATTERN.match(slug):
        raise ValidationError(
            f"slug {slug!r} is not acceptable. Use lowercase letters, digits "
            f"and hyphens, starting with a letter or digit, at most 64 "
            f"characters (SEC-1.1)."
        )
    if slug.split(".")[0] in _WINDOWS_DEVICES:
        raise ValidationError(
            f"slug {slug!r} is a reserved Windows device name; it cannot be a "
            f"directory on every platform this runs on"
        )
    if slug.endswith("-"):
        raise ValidationError(f"slug {slug!r} ends with a hyphen")
    if "--" in slug:
        raise ValidationError(
            f"slug {slug!r} contains a double hyphen; two slugs that differ "
            f"only in hyphen runs are too easy to confuse in a directory listing"
        )
    return slug


def validate_premise(premise: str) -> str:
    """Return ``premise`` unchanged, or raise.

    Bounded in length and refused if it carries characters that hide text from
    a human reviewer. Its *content* is not judged (SEC-1.3).
    """
    if not isinstance(premise, str):
        raise ValidationError(f"premise must be a string, got {type(premise).__name__}")

    stripped = premise.strip()
    if len(stripped) < MIN_PREMISE_CHARS:
        raise ValidationError(
            f"premise is {len(stripped)} characters; at least "
            f"{MIN_PREMISE_CHARS} are needed for the worldbuilder to have "
            f"anything to work from"
        )
    if len(premise) > MAX_PREMISE_CHARS:
        raise ValidationError(
            f"premise is {len(premise)} characters, over the "
            f"{MAX_PREMISE_CHARS} limit. A premise is a seed, not an outline - "
            f"the outline is FLOW-3's job."
        )

    # SEC-1.4. A premise carrying a credential is a paste accident, and the
    # premise is the one input that reaches the Story Bible verbatim - from
    # there it spreads into the manuscript, which the redactor deliberately
    # does not touch because scrubbing an author's prose is its own
    # corruption. Refusing at the door is the only place this can be caught.
    from .secrets import Redactor
    if Redactor().finds_secret(premise):
        raise ValidationError(
            "premise appears to contain a credential. It would be written "
            "verbatim into bible/world.md and from there into the "
            "manuscript, which is not redacted - a novel is prose, not a "
            "log. Remove the secret and try again (SEC-1.4)."
        )

    invisible = _invisible_characters(premise)
    if invisible:
        index, char, category = invisible[0]
        raise ValidationError(
            f"premise contains a {category} character (U+{ord(char):04X}) at "
            f"position {index}. Characters in Cc/Cf are invisible to a human "
            f"reviewing this text and fully visible to the model reading it, "
            f"so they are refused rather than stripped (SEC-1.2). "
            f"{len(invisible)} in total."
        )
    return premise
