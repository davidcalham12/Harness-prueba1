"""The Length Critic - arithmetic, not an agent.

It is in the gate alongside two model-driven critics on purpose. Length is the
one quality the config states exactly, so it is the one the harness can check
*without* asking a model whether the answer looks right. When a run reports
``length 10/10`` on every chapter, that is not a model being agreeable; it is
``len(text.split())`` falling inside the band the config asked for.

And when it does not, the chapter is rewritten, which is what makes
``words_per_chapter`` a setting rather than a suggestion.
"""

from __future__ import annotations

from ..domain.models import Critique, Finding
from ..textops import count_lines, count_paragraphs, count_words, paragraphs, wrap_paragraph
from .base import CriticContext, score_from_findings

__all__ = ["LengthCritic"]


class LengthCritic:
    """Measures the draft against the configured bands."""

    name = "length"

    def review(self, context: CriticContext) -> Critique:
        from ..textops import chapter_body

        body = chapter_body(context.text)
        words = count_words(body)
        paras = paragraphs(body)
        width = int(context.bands("chars_per_line_max", 84))

        # Count lines as the manuscript will actually be wrapped, not as the
        # draft happens to be laid out. Otherwise the critic measures the
        # model's newlines, which no reader ever sees.
        wrapped_lines = sum(len(wrap_paragraph(" ".join(p.split()), width)) for p in paras)

        findings: list[Finding] = []
        detail = {
            "words": words,
            "lines": wrapped_lines,
            "paragraphs": len(paras),
            "wrap_width": width,
        }

        w_min = int(context.bands("words_min", 0))
        w_max = int(context.bands("words_max", 10 ** 9))
        if words < w_min:
            findings.append(Finding(
                kind="too-short", severity="high",
                quote=f"{words} words",
                fix=f"Expand to at least {w_min} words without adding new canon.",
                reference=f"novel.words_per_chapter.min = {w_min}",
            ))
        elif words > w_max:
            findings.append(Finding(
                kind="too-long", severity="high",
                quote=f"{words} words",
                fix=f"Cut to at most {w_max} words; drop repetition, not beats.",
                reference=f"novel.words_per_chapter.max = {w_max}",
            ))

        p_min = int(context.bands("paragraphs_min", 0))
        p_max = int(context.bands("paragraphs_max", 10 ** 9))
        if len(paras) < p_min:
            findings.append(Finding(
                kind="too-few-paragraphs", severity="medium",
                quote=f"{len(paras)} paragraphs",
                fix=f"Break the prose into at least {p_min} paragraphs.",
                reference=f"novel.paragraphs_per_chapter.min = {p_min}",
            ))
        elif len(paras) > p_max:
            findings.append(Finding(
                kind="too-many-paragraphs", severity="medium",
                quote=f"{len(paras)} paragraphs",
                fix=f"Merge related paragraphs; at most {p_max}.",
                reference=f"novel.paragraphs_per_chapter.max = {p_max}",
            ))

        l_min = int(context.bands("lines_min", 0))
        l_max = int(context.bands("lines_max", 10 ** 9))
        if not (l_min <= wrapped_lines <= l_max):
            findings.append(Finding(
                kind="line-count-out-of-band", severity="low",
                quote=f"{wrapped_lines} lines at {width} columns",
                fix=f"Target {l_min}-{l_max} wrapped lines.",
                reference=f"novel.lines_per_chapter = {l_min}-{l_max}",
            ))

        return Critique(
            critic=self.name,
            score=score_from_findings(findings),
            findings=tuple(findings),
            detail=detail,
        )
