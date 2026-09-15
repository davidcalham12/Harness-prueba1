"""The Science Auditor - does the draft break a rule the world declared?

Each check is **conditional on the canon**. A chapter only fails for mentioning
a warp drive if ``bible/world.md`` actually contains a rule forbidding
faster-than-light travel. A setting that permits FTL is not wrong for using it,
and a critic that thought otherwise would be enforcing its own physics instead
of the book's.

So the table below is a set of *if the world said this, then this contradicts
it* pairs, and a run against a different Story Bible audits against different
rules with no code change.
"""

from __future__ import annotations

import re

from ..domain.models import Critique, Finding
from ..textops import chapter_body
from .base import CriticContext, score_from_findings

__all__ = ["ScienceCritic", "VIOLATIONS"]

# (rule keywords, violating phrases, what to do about it)
VIOLATIONS: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    (
        ("faster-than-light", "faster than light", "ftl", "months", "arrives late"),
        ("warp drive", "hyperspace", "jump drive", "lightspeed", "light speed",
         "instantaneous transmission", "real-time call", "subspace"),
        "The world forbids faster-than-light travel and instant messages; "
        "the crossing takes months and every signal arrives late.",
    ),
    (
        ("inertia", "thrust is felt", "hard burn"),
        ("inertial dampener", "inertial damper", "artificial gravity plating",
         "antigrav", "anti-grav", "gravity generator"),
        "Inertia is never cancelled in this world. Let the burn cost the crew "
        "something physical.",
    ),
    (
        ("vacuum", "silent", "nothing outside the hull is ever heard"),
        ("heard the explosion outside", "sound carried across the vacuum",
         "roar of the engines outside", "echoed through space"),
        "Vacuum is silent here. Sound reaches the crew through the hull, "
        "never through space.",
    ),
    (
        ("echo core", "never copied", "read in place"),
        ("copied the core", "downloaded the core", "duplicated the echo core",
         "backed up the core"),
        "An echo core can be read in place but never copied. Going to it is "
        "the cost the plot is built on.",
    ),
)


class ScienceCritic:
    """Holds the draft against the rules in ``bible/world.md``."""

    name = "science"

    def review(self, context: CriticContext) -> Critique:
        body = chapter_body(context.text)
        lowered = body.lower()
        canon = " ".join(context.world_rules).lower()

        findings: list[Finding] = []
        checked: list[str] = []

        for keywords, phrases, fix in VIOLATIONS:
            if not any(keyword in canon for keyword in keywords):
                continue  # the world never made this claim; nothing to enforce
            checked.append(keywords[0])
            for phrase in phrases:
                index = lowered.find(phrase)
                if index == -1:
                    continue
                # Quote the surrounding sentence, not the bare phrase: the
                # writer has to find it in the draft to fix it.
                start = max(0, lowered.rfind(".", 0, index) + 1)
                end = lowered.find(".", index)
                end = len(body) if end == -1 else end + 1
                findings.append(Finding(
                    kind="physics-violation",
                    severity="high",
                    quote=" ".join(body[start:end].split()),
                    fix=fix,
                    reference="bible/world.md § Rules",
                ))
                break

        return Critique(
            critic=self.name,
            score=score_from_findings(findings),
            findings=tuple(findings),
            detail={"rules_enforced": checked, "rules_in_canon": len(context.world_rules)},
        )
