"""FLOW-1 and FLOW-2 - the only two stages that write the Story Bible.

Both take their prompt from ``.claude/skills/<agent>/SKILL.md`` and call
``context.bible.write(..., role=stage.agent)``. The role is the one
the orchestrator invoked, taken from the spec, never from anything the model
emitted - which is what makes
:func:`~novaforge.security.prompting.assert_may_write_bible` a guarantee rather
than a request (SEC-4.3).

The two are separate stages, not one, because FLOW-2 needs FLOW-1's output as
input: the cast is built against a world that already exists. Splitting them is
also what lets the spec grant Bible authority to exactly two agents instead of
one catch-all "setup" step.
"""

from __future__ import annotations

from .base import StageContext, StageResult

__all__ = ["BibleSectionStage", "BibleMultiSectionStage"]


class BibleSectionStage:
    """FLOW-1: one Bible section from the premise."""

    def run(self, context: StageContext) -> StageResult:
        section = "world"
        completion = context.call(
            role=context.spec.agent,
            system=context.agent.system(
                agent=context.spec.agent.replace("_", " "),
                tone=context.config.get("novel.tone")),
            prompt=f"Premise: {context.premise}",
            task={
                "kind": section,
                "premise": context.premise,
                "tone": context.config.get("novel.tone"),
                "rules": context.config.get("bible.world_rules.min"),
                "technology": context.config.get("bible.technology_entries.min"),
                "factions": context.config.get("bible.factions.min"),
            },
        )
        path = context.bible.write(section, completion.text, role=context.spec.agent)
        rules = len(context.bible.world_rules())
        context.report(f"    wrote {path} ({len(completion.text.split())} words, {rules} rules)")
        return StageResult(artefacts=(path,), usage=completion.usage)


class BibleMultiSectionStage:
    """FLOW-2: cast, timeline and mysteries, in that order.

    Order matters: the timeline and the mysteries both name characters, so the
    cast has to be canonical before either is written. Getting this backwards
    is how a timeline ends up referring to someone who does not exist.
    """

    SECTIONS = ("characters", "timeline", "mysteries")

    def run(self, context: StageContext) -> StageResult:
        artefacts: list[str] = []
        usage = None
        tasks = {
            "characters": {"characters": context.config.get("bible.characters.min")},
            "timeline": {"rows": context.config.get("bible.timeline_rows.min")},
            "mysteries": {"mysteries": context.config.get("bible.mysteries.min")},
        }
        for section in self.SECTIONS:
            completion = context.call(
                role=context.spec.agent,
                system=context.agent.system(
                    agent=context.spec.agent.replace("_", " "),
                    tone=context.config.get("novel.tone")),
                prompt=(
                    f"Premise: {context.premise}\n\n"
                    f"The world, as established:\n{context.bible.as_context(('world',))}"
                ),
                task={"kind": section, "section": section,
                      "premise": context.premise, **tasks[section]},
            )
            path = context.bible.write(section, completion.text, role=context.spec.agent)
            artefacts.append(path)
            usage = completion.usage if usage is None else usage + completion.usage
            extra = ""
            if section == "characters":
                extra = f", {len(context.bible.characters())} characters"
            context.report(f"    wrote {path} ({len(completion.text.split())} words{extra})")
        return StageResult(artefacts=tuple(artefacts), usage=usage)
