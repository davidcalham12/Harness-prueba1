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

from ..export import build_exporters
from ..textops import count_words
from .base import StageContext, StageResult

__all__ = ["PublishStage"]


class PublishStage:
    """Synopsis, then the manuscript."""

    def run(self, context: StageContext) -> StageResult:
        finals = context.workspace.glob("chapters/*.final.md")
        if not finals:
            raise ValueError("publish found no final chapters; FLOW-5 did not run")
        chapters = [context.workspace.read_text(path) for path in finals]

        completion = context.call(
            role=context.spec.agent,
            system=context.agent.system(
                tone=context.config.get("novel.tone"),
                min_words=context.config.get("outputs.synopsis.words.min"),
                max_words=context.config.get("outputs.synopsis.words.max"),
                comparables=context.config.get("outputs.synopsis.comparables.min")),
            prompt=f"Premise: {context.premise}\n\nCanon:\n{context.bible.as_context()}",
            task={
                "kind": "synopsis",
                "premise": context.premise,
                "min_words": context.config.get("outputs.synopsis.words.min"),
                "comparables": context.config.get("outputs.synopsis.comparables.min"),
                "names": [c.name for c in context.bible.characters()],
            },
        )
        context.workspace.write_text("synopsis.md", content=completion.text.strip() + "\n")

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
        for name in missing:
            notes.append(f"outputs.formats asks for {name!r}, which this build cannot write")
            context.report(f"    NOT WRITTEN: {name} — no exporter in this build")

        return StageResult(
            artefacts=tuple(artefacts),
            usage=completion.usage,
            notes=tuple(notes),
            data={"synopsis_words": synopsis_words, "missing_formats": missing},
        )
