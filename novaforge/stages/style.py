"""FLOW-5 - one voice across chapters written in isolation.

The chapters were written independently of each other by design, which is what
keeps the context bounded - and it is also the one place that design shows a
seam. Punctuation habits and spacing drift between chapters that never saw each
other.

This pass closes that seam and is deliberately limited to doing so. It
normalises presentation; it does not rewrite sentences. A style pass that
changed the prose would invalidate the critique the chapter just passed - the
gate would have approved text that is no longer the text being published.

So the limit is enforced rather than requested: output whose word count moved,
or that carries a sentence addressed to the operator, is **discarded** and the
approved draft published instead. That matters here more than anywhere,
because this stage runs *after* the gate and nothing downstream would catch
it.
"""

from __future__ import annotations

from ..response import find_chatter
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
            chatter = find_chatter(completion.text)
            styled = completion.text

            # This stage's whole contract is that it changes no content. When
            # its output breaks that - a moved word count, or a sentence
            # addressed to the operator - the output is not usable and the
            # approved draft is. Discarding loses nothing, because everything
            # this pass legitimately does is presentational.
            #
            # It matters more here than anywhere: FLOW-5 runs *after* the gate,
            # so nothing downstream would catch it. An editor that appended
            # "Happy to expand any section further." would publish it.
            if before != after or chatter:
                drift += 1
                why = (f"word count moved {before} -> {after}" if before != after
                       else f"chatter: {chatter[0]['quote'][:60]}")
                context.report(f"    {source}: style pass discarded ({why})")
                context.log({"event": "style_discarded", "flow_id": context.spec.id,
                             "source": source, "words_before": before,
                             "words_after": after, "chatter": chatter})
                styled = original

            target = source.replace(".md", ".final.md")
            context.workspace.write_text(target, content=styled)
            artefacts.append(target)

        context.report(
            f"    wrote {len(artefacts)} final chapters"
            + (f", {drift} discarded and kept as approved" if drift
               else ", no content changed")
        )
        return StageResult(artefacts=tuple(artefacts), usage=usage)
