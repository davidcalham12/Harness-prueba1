"""Building the Chapter Writer's context - and proving what is not in it.

`specs/flow.yaml` FLOW-4 declares a ``context_policy``: the writer gets the
Story Bible, this chapter's outline entry, and a capped rolling summary, and
**no prior chapter prose**. That is the architectural claim of the whole
project, so it is enforced here at runtime rather than merely requested in a
prompt: :func:`assert_no_prior_prose` re-reads the assembled prompt and raises
if any earlier chapter's wording leaked into it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .domain.models import ChapterPlan, Finding
from .security.prompting import wrap_untrusted
from .textops import chapter_body

__all__ = [
    "ChapterContext",
    "ContextPolicyViolation",
    "assert_no_prior_prose",
    "build_chapter_context",
    "roll_summary",
]

# A run of this many consecutive words shared with an earlier chapter is
# treated as leaked prose. Short enough to catch a paragraph, long enough that
# a repeated character name or a stock phrase does not trip it. The running
# value is `context.leak_window_words` in the config; this is the fallback for
# callers that have no config (CFG-5.1).
LEAK_WINDOW = 10


class ContextPolicyViolation(AssertionError):
    """The assembled prompt breaks the context policy declared in the flow spec."""


@dataclass(frozen=True)
class ChapterContext:
    """Exactly what the writer is allowed to see, and nothing else."""

    bible: str
    plan_block: str
    summary: str
    findings_block: str = ""

    def render(self, *, include_summary: bool = True) -> str:
        """The writer's context.

        ``include_summary=False`` renders everything *except* the rolling
        summary. The summary is the one sanctioned channel for prior-chapter
        material - it is extractive, so it legitimately shares wording with
        earlier chapters - and excluding it is what lets
        :func:`assert_no_prior_prose` check the rest of the prompt strictly.
        """
        parts = [self.bible, self.plan_block]
        if include_summary:
            parts.append(
                wrap_untrusted("story-so-far", self.summary)
                if self.summary.strip()
                else '<untrusted source="story-so-far">\n(this is the first chapter)\n</untrusted>'
            )
        if self.findings_block.strip():
            parts.append(self.findings_block)
        return "\n\n".join(part for part in parts if part.strip())

    @property
    def summary_words(self) -> int:
        return len(self.summary.split())


def _plan_markdown(plan: ChapterPlan) -> str:
    beats = "\n".join(f"  - {beat}" for beat in plan.beats) or "  - (no beats given)"
    return (
        f"### Chapter {plan.number} — {plan.title}\n"
        f"- **POV:** {plan.pov}\n"
        f"- **Tension:** {plan.tension}/10\n"
        f"- **Promise advanced:** {plan.promise}\n"
        f"- **Beats:**\n{beats}\n"
    )


def _findings_markdown(findings: Sequence[Finding]) -> str:
    if not findings:
        return ""
    lines = [
        "The previous draft did not clear the quality gate. Fix every item below,",
        "and change nothing else:",
        "",
    ]
    for index, finding in enumerate(findings, start=1):
        lines.append(f"{index}. [{finding.severity}] {finding.kind} — {finding.fix}")
        lines.append(f"   offending text: {finding.quote!r}")
        if finding.reference:
            lines.append(f"   canon: {finding.reference}")
    return "\n".join(lines)


def roll_summary(previous: Iterable[str], max_words: int = 200) -> str:
    """Fold prior chapter summaries into one capped block.

    Oldest first, truncated from the end, so the chapter immediately before
    this one is the part that gets dropped last.
    """
    words: list[str] = []
    for summary in previous:
        words.extend((summary or "").split())
    if len(words) <= max_words:
        return " ".join(words).strip()
    return " ".join(words[-max_words:]).strip()


def build_chapter_context(
    *,
    bible_context: str,
    plan: ChapterPlan,
    summary_so_far: str,
    max_summary_words: int = 200,
    findings: Sequence[Finding] = (),
) -> ChapterContext:
    """Assemble the writer's context under the flow spec's policy."""
    summary = " ".join((summary_so_far or "").split()[:max_summary_words])
    return ChapterContext(
        bible=bible_context,
        plan_block=wrap_untrusted(f"outline.md#chapter-{plan.number:02d}", _plan_markdown(plan)),
        summary=summary,
        findings_block=_findings_markdown(findings),
    )


def assert_no_prior_prose(
    prompt: str,
    prior_chapters: Iterable[str],
    *,
    canon: str = "",
    window: int = LEAK_WINDOW,
) -> None:
    """Raise if any earlier chapter's prose appears in the prompt.

    Runtime enforcement of FLOW-4 ``forbid_prior_chapter_prose``. Pass the
    prompt rendered **without** the rolling summary
    (:meth:`ChapterContext.render` with ``include_summary=False``): the summary
    is extractive and legitimately shares wording with earlier chapters, and is
    bounded separately by ``max_summary_words``.

    ``canon`` is the Story Bible and this chapter's outline entry. Runs that
    also occur there are skipped, because a chapter that quotes a rule from
    ``world.md`` would otherwise make that rule un-passable for every later
    chapter. So the guarantee this function actually gives, stated exactly: *no
    run of ten consecutive words from an earlier chapter reaches the writer,
    unless that run is also in the canon the writer is entitled to see.*
    """
    span = max(3, int(window))
    haystack = " ".join(prompt.split())
    allowed = " ".join((canon or "").split())
    for index, chapter in enumerate(prior_chapters, start=1):
        words = chapter_body(chapter).split()
        if len(words) < span:
            continue
        for start in range(0, len(words) - span + 1):
            run = " ".join(words[start : start + span])
            if run in haystack and (not allowed or run not in allowed):
                raise ContextPolicyViolation(
                    f"chapter {index} prose leaked into the writer's prompt: {run!r}. "
                    "FLOW-4 context_policy forbids prior chapter prose."
                )
