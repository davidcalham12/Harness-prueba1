"""FLOW-3 - the outline.

This is the last stage that sees the whole book at once. Everything after it
works one chapter at a time, and the outline is what carries the shape of the
novel across that boundary: each :class:`~novaforge.domain.models.ChapterPlan`
is the entire plot context its chapter's writer will get.

So a thin outline entry is not a cosmetic problem. A chapter whose plan has no
beats is a chapter written from nothing but the Bible and a title.
"""

from __future__ import annotations

from ..domain.models import ChapterPlan, Outline
from ..textops import parse_outline
from .base import StageContext, StageResult

__all__ = ["OutlineStage"]


class OutlineStage:
    """Acts, per-chapter tension curve and reader promises."""

    def run(self, context: StageContext) -> StageResult:
        chapters = int(context.config.get("novel.chapters"))
        completion = context.call(
            role=context.spec.agent,
            system=context.agent.system(
                tone=context.config.get("novel.tone"), chapters=chapters),
            prompt=(
                f"Premise: {context.premise}\n\n"
                f"Canon:\n{context.bible.as_context()}\n\n"
                f"Write {chapters} chapters."
            ),
            task={
                "kind": "outline",
                "chapters": chapters,
                "beats": context.config.get("novel.beats_per_chapter.min"),
                "promises": context.config.get("bible.mysteries.min"),
                "characters": context.config.get("bible.characters.min"),
            },
        )
        context.workspace.write_text("outline.md", content=completion.text.rstrip() + "\n")

        rows = parse_outline(completion.text)
        if not rows:
            raise ValueError(
                "the outline stage produced no parseable chapter entries; "
                "expected '### Chapter N — Title' headings"
            )

        plans: list[ChapterPlan] = []
        thin: list[str] = []
        for row in rows[:chapters]:
            plan = ChapterPlan(
                number=int(row["number"]),
                title=str(row["title"]),
                pov=str(row["pov"]),
                tension=int(row["tension"]),
                promise=str(row["promise"]),
                beats=tuple(str(b) for b in row["beats"]),  # type: ignore[arg-type]
            )
            if not plan.beats:
                thin.append(f"chapter {plan.number} has no beats")
            plans.append(plan)

        if len(plans) != chapters:
            raise ValueError(
                f"outline has {len(plans)} chapters, config asks for {chapters}"
            )

        outline = Outline(plans=tuple(plans))
        curve = ", ".join(str(p.tension) for p in plans)
        context.report(f"    wrote outline.md ({len(plans)} chapters, tension {curve})")
        for note in thin:
            context.report(f"    warning: {note}")

        return StageResult(
            artefacts=("outline.md",),
            usage=completion.usage,
            notes=tuple(thin),
            data={"outline": outline},
        )
