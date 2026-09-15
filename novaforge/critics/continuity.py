"""The Continuity Critic - does the draft contradict the canon?

The check that matters for the demo is **name drift**: a surname that is one
edit away from a canonical one, and is not itself canonical. That is the shape
of the error a model actually makes when it writes a chapter without seeing the
previous one - not inventing a new character, but half-remembering an existing
one.

It is detected against ``bible/characters.md``, never against earlier chapters.
Comparing chapters to each other would reintroduce exactly the dependency the
context policy removes, and would get slower with every chapter written.
"""

from __future__ import annotations

import re

from ..domain.models import Critique, Finding
from ..textops import chapter_body
from .base import CriticContext, score_from_findings

__all__ = ["ContinuityCritic", "edit_distance"]

_WORD = re.compile(r"\b[A-Z][a-z]{2,}\b")

# Words that are capitalised because they start a sentence or name a place, not
# because they are a character. Without this the critic reports the first word
# of every paragraph as a drifted surname.
_STOPWORDS = frozenset({
    "The", "There", "They", "Then", "That", "This", "These", "Those", "Their",
    "Nothing", "Somewhere", "Something", "Someone", "Salvage", "Power", "Vacuum",
    "Inertia", "Chapter", "Contact", "When", "What", "Where", "Which", "With",
    "And", "But", "For", "Not", "Now", "One", "Two", "Three", "His", "Her",
    "She", "Him", "Had", "Has", "Was", "Were", "Been", "Because", "Before",
    "After", "Against", "Aboard", "Above", "Below", "Outside", "Inside", "It",
    "Its", "Every", "Each", "Only", "Even", "Still", "Never", "Always",
})


def edit_distance(a: str, b: str, *, cap: int = 3) -> int:
    """Levenshtein distance, abandoned once it exceeds ``cap``.

    The cap is not just an optimisation: past two or three edits the words are
    different words, and reporting them as a misspelling would be noise.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    previous = list(range(len(b) + 1))
    for i, ch_a in enumerate(a, start=1):
        current = [i]
        for j, ch_b in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ch_a != ch_b),
            ))
        if min(current) > cap:
            return cap + 1
        previous = current
    return previous[-1]


class ContinuityCritic:
    """Holds the draft against ``bible/characters.md``."""

    name = "continuity"

    def review(self, context: CriticContext) -> Critique:
        body = chapter_body(context.text)
        canonical_full = {c.name for c in context.characters}
        canonical_parts = set()
        for character in context.characters:
            canonical_parts.update(character.name.split())

        findings: list[Finding] = []
        reported: set[str] = set()

        for match in _WORD.finditer(body):
            token = match.group(0)
            if token in canonical_parts or token in _STOPWORDS or token in reported:
                continue
            for character in context.characters:
                surname = character.surname
                if len(surname) < 3:
                    continue
                distance = edit_distance(token, surname)
                if 0 < distance <= 1:
                    reported.add(token)
                    findings.append(Finding(
                        kind="name-drift",
                        severity="high",
                        quote=token,
                        fix=f"Use the canonical spelling {surname!r} "
                            f"({character.name}).",
                        reference="bible/characters.md",
                    ))
                    break

        present = sorted({c.name for c in context.characters
                          if c.surname and re.search(r"\b" + re.escape(c.surname) + r"\b", body)})
        if context.characters and not present:
            findings.append(Finding(
                kind="no-canonical-character",
                severity="medium",
                quote=" ".join(body.split()[:12]) + "…",
                fix="Name at least one character from the Story Bible.",
                reference="bible/characters.md",
            ))

        return Critique(
            critic=self.name,
            score=score_from_findings(findings),
            findings=tuple(findings),
            detail={
                "characters_present": present,
                "canonical_cast": sorted(canonical_full),
            },
        )
