"""Is the draft addressed to the reader, or to whoever asked for it?

A model returning a chapter often returns a sentence either side of it -
"Certainly. Below is the chapter." or "Let me know if you'd like me to adjust
the tone." The mechanical half of that is removed in
:mod:`novaforge.response`; this is the half that is a judgement.

**It is a critic rather than a text filter on purpose.** "Let me know if you
need anything else" is chatter at the end of a chapter and dialogue in the
middle of one, and a program that deleted the second to catch the first would
be a program that edits an author's prose on a guess. So it is reported,
quoted, and handed back to the writer by the same loop that handles a drifted
surname - which is exactly what the gate is for.
"""

from __future__ import annotations

from ..domain.models import Critique, Finding
from ..response import find_chatter
from .base import CriticContext, score_from_findings

__all__ = ["ChatterCritic"]


class ChatterCritic:
    """Flags text written to the operator rather than to the reader."""

    name = "chatter"

    def review(self, context: CriticContext) -> Critique:
        hits = find_chatter(context.text)
        findings = [
            Finding(
                kind=hit["kind"],
                severity="high",
                quote=hit["quote"],
                fix="Remove this. It is addressed to whoever asked for the "
                    "chapter, not to whoever reads it, and it would be "
                    "published as prose and counted as words.",
                reference=".claude/skills/chapter_writer/SKILL.md",
            )
            for hit in hits
        ]
        return Critique(
            critic=self.name,
            score=score_from_findings(findings),
            findings=tuple(findings),
            detail={"paragraphs_examined": "first and last two"},
        )
