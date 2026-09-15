"""FLOW-5 - one voice across chapters written in isolation.

The chapters were written independently of each other by design, which is what
keeps the context bounded - and it is also the one place that design shows a
seam. Punctuation habits and spacing drift between chapters that never saw each
other.

This pass closes that seam and is deliberately limited to doing so. It
normalises presentation; it does not rewrite sentences. A style pass that
changed the prose would invalidate the critique the chapter just passed - the
gate would have approved text that is no longer the text being published.
"""

from __future__ import annotations

from ..textops import count_words
from .base import StageContext, StageResult

__all__ = ["StylePassStage"]


class StylePassStage:
    """Writes ``chapters/chNN.final.md`` for every approved chapter."""

    def run(self, context: StageContext) -> StageResult:
        sources = [p for p in context.workspace.glob("chapters/*.md")
                   if not p.endswith(".final.md") and not p.endswith(".summary.md")]
        if not sources:
            raise ValueError("style pass found no chapters to edit")

        artefacts: list[str] = []
        usage = None
        drift = 0

        for source in sources:
            original = context.workspace.read_text(source)
            completion = context.call(
                role=context.spec.agent,
                system=context.agent.system(
                    tone=context.config.get("novel.tone")),
                prompt="(style pass)",
                task={"kind": "style", "text": original},
            )
            usage = completion.usage if usage is None else usage + completion.usage

            before, after = count_words(original), count_words(completion.text)
            if before != after:
                # Worth reporting rather than silently accepting: it means the
                # editor changed content, which is not what this stage is for.
                drift += 1
                context.report(
                    f"    warning: {source} word count moved {before} -> {after}"
                )

            target = source.replace(".md", ".final.md")
            context.workspace.write_text(target, content=completion.text)
            artefacts.append(target)

        context.report(
            f"    wrote {len(artefacts)} final chapters"
            + (f", {drift} with word-count drift" if drift else ", no content changed")
        )
        return StageResult(artefacts=tuple(artefacts), usage=usage)
