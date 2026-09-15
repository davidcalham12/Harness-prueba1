"""FLOW-6 - synopsis from the model, artefacts from code.

The split is deliberate. The synopsis is a judgement about what the book is
about, which is a model's job. The manuscript is a mechanical transformation of
approved text into a file, which is not - and a model asked to "assemble the
book" would silently paraphrase a sentence somewhere in the middle, after the
gate had already approved it.

Which formats are written is ``outputs.formats``. A format the config asks for
and this build cannot produce is reported by name: a run that quietly writes
one file when the config asked for two is a run that lies in its summary.
"""

from __future__ import annotations

from dataclasses import replace

from ..export import build_exporters
from ..response import find_chatter, strip_chatter
from ..textops import count_words
from .base import StageContext, StageResult

__all__ = ["PublishStage"]


class PublishStage:
    """Synopsis, then the manuscript."""

    def _ask(self, context, attempt):
        return context.call(
            role=context.spec.agent,
            system=context.agent.system(
                tone=context.config.get("novel.tone"),
                min_words=context.config.get("outputs.synopsis.words.min"),
                max_words=context.config.get("outputs.synopsis.words.max"),
                comparables=context.config.get("outputs.synopsis.comparables.min")),
            prompt=(f"Premise: {context.premise}\n\n"
                    f"Canon:\n{context.bible.as_context()}"),
            task={
                "kind": "synopsis",
                "premise": context.premise,
                "min_words": context.config.get("outputs.synopsis.words.min"),
                "comparables": context.config.get("outputs.synopsis.comparables.min"),
                "names": [c.name for c in context.bible.characters()],
                "attempt": attempt,
            },
        )

    def run(self, context: StageContext) -> StageResult:
        finals = context.workspace.glob("chapters/*.final.md")
        if not finals:
            raise ValueError("publish found no final chapters; FLOW-5 did not run")
        chapters = [context.workspace.read_text(path) for path in finals]

        # FLOW-6 has no gate, so a synopsis that came back opening "Certainly.
        # Below is the synopsis." would be published as the book's first
        # paragraph. Asking again costs one call and usually fixes it; if it
        # does not, the run says so rather than shipping it quietly.
        chatter: list = []
        for attempt in (1, 2):
            completion = self._ask(context, attempt)
            chatter = find_chatter(completion.text)
            if not chatter:
                break
            context.report(
                f"    synopsis is addressed to the operator "
                f"({chatter[0]['quote'][:44]}...); asking again"
                if attempt == 1 else
                "    synopsis still carries operator-facing text; trimming it"
            )

        text = completion.text
        removed: list = []
        if chatter:
            # The last resort, and the only place in the program that does it.
            # A synopsis is generated marketing copy with no gate behind it; a
            # chapter in the same position is sent back to its writer instead.
            # Whole paragraphs go, never sentences, and what went is reported.
            text, removed = strip_chatter(text)
            for cut in removed:
                context.report(f"    dropped from the synopsis ({cut['where']}): "
                               f"{cut['quote'][:56]}")
            completion = replace(completion, text=text)

        context.workspace.write_text("synopsis.md", content=text.strip() + "\n")

        synopsis_words = count_words(completion.text)
        band = (context.config.get("outputs.synopsis.words.min"),
                context.config.get("outputs.synopsis.words.max"))
        note = "" if band[0] <= synopsis_words <= band[1] else \
            f" (outside the {band[0]}-{band[1]} band)"
        context.report(f"    wrote synopsis.md ({synopsis_words} words{note})")

        formats = context.config.get("outputs.formats")
        exporters, missing = build_exporters(formats)

        artefacts = ["synopsis.md"]
        for exporter in exporters:
            result = exporter.export(
                workspace=context.workspace,
                config=context.config,
                chapters=chapters,
                synopsis=completion.text,
            )
            artefacts.append(result.path)
            context.report(f"    wrote {result.path} — {result.detail}")

        notes: list[str] = []
        for cut in removed:
            notes.append(f"dropped operator-facing text from the synopsis "
                         f"({cut['where']}): {cut['quote'][:60]}")
        for name in missing:
            notes.append(f"outputs.formats asks for {name!r}, which this build cannot write")
            context.report(f"    NOT WRITTEN: {name} — no exporter in this build")

        return StageResult(
            artefacts=tuple(artefacts),
            usage=completion.usage,
            notes=tuple(notes),
            data={"synopsis_words": synopsis_words, "missing_formats": missing},
        )
