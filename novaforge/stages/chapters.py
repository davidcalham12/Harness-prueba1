"""FLOW-4 - draft each chapter, then hold it against the critics.

This stage is the reason the project exists, and two things in it are load
bearing:

**The writer never sees prior prose.** The context is the Story Bible, this
chapter's outline entry, and a capped rolling summary - and that is enforced,
not requested. :func:`~novaforge.context.assert_no_prior_prose` re-reads the
assembled prompt before it is sent and raises if any earlier chapter's wording
reached it. The prompt is checked *without* the rolling summary, because the
summary is extractive and legitimately shares wording; it is bounded separately
by ``max_summary_words``.

**The gate is the config's, not this file's.** The threshold, the critic list,
the aggregate and the draft allowance all arrive on ``stage.gate``, put there
by :func:`novaforge.spec.flow.apply_config`. There is no threshold literal
here, which is why changing ``quality_gate.threshold`` in JSON changes what
this loop accepts.

On the last allowed draft the ``on_fail`` policy decides: ``halt`` stops the
run, ``accept_with_warnings`` keeps the **best** draft seen - not the last one,
which would throw away a better earlier attempt for no reason.
"""

from __future__ import annotations

from ..context import assert_no_prior_prose, build_chapter_context, roll_summary
from ..critics import build_critics
from ..critics.base import CriticContext
from ..domain.models import ChapterRecord, Critique, Finding, GateDecision
from ..security.prompting import UNTRUSTED_CLAUSE
from ..textops import chapter_body, count_words, wrap_paragraph, paragraphs
from .base import StageContext, StageResult

__all__ = ["ChapterLoopStage", "GateHalted"]

class GateHalted(RuntimeError):
    """A chapter never cleared the gate and the policy is ``halt``."""


class ChapterLoopStage:
    """Per-chapter draft-critique-rewrite loop."""

    def run(self, context: StageContext) -> StageResult:
        gate = context.spec.gate
        if gate is None:
            raise ValueError("FLOW-4 requires a gate; the spec declared none")
        if context.outline is None:
            raise ValueError("the chapter loop needs an outline; FLOW-3 did not run")

        critics = build_critics(gate.critics)
        bands = context.chapter_bands()
        policy = dict(context.spec.context_policy)
        max_summary = int(policy.get("max_summary_words",
                                     context.config.get("context.max_summary_words")))
        enforce = bool(policy.get("forbid_prior_chapter_prose", True))
        leak_window = int(context.config.get("context.leak_window_words"))

        cast = context.bible.characters()
        rules = context.bible.world_rules()
        names = [c.name for c in cast]
        bible_context = context.bible.as_context()

        artefacts: list[str] = []
        usage = None
        summaries: list[str] = []
        prior_chapters: list[str] = []
        records: list[ChapterRecord] = []
        decisions: list[GateDecision] = []

        header = (f"gate {'+'.join(gate.critics)} >= {gate.threshold}, "
                  f"max {gate.max_iterations} drafts, on_fail={context.spec.on_fail}")
        context.report(f"    {header}")

        done = self._already_done(context)

        for plan in context.outline:
            # Resume at chapter granularity, not stage granularity. A run that
            # lost one chapter should cost one chapter to repair, so a chapter
            # whose prose is on disk and whose state says it cleared the gate
            # is reloaded rather than rewritten.
            reused = self._reuse(context, plan, done, bands, artefacts)
            if reused is not None:
                record, text, summary = reused
                records.append(record)
                prior_chapters.append(text)
                summaries.append(summary)
                context.report(
                    f"    ch{plan.number:02d} already {record.status}, reused "
                    f"({record.words} words, no call)"
                )
                continue

            findings: tuple[Finding, ...] = ()
            best: tuple[int, str, dict[str, Critique]] | None = None
            record: ChapterRecord | None = None
            # Every draft's verdict, kept per critic. The rejected drafts are
            # the evidence that the gate did something, so they are written to
            # `critiques/` alongside the accepted one rather than overwritten
            # by it.
            history: dict[str, list[Critique]] = {c.name: [] for c in critics}

            for iteration in range(1, gate.max_iterations + 1):
                chapter_context = build_chapter_context(
                    bible_context=bible_context,
                    plan=plan,
                    summary_so_far=roll_summary(summaries, max_words=max_summary),
                    max_summary_words=max_summary,
                    findings=findings,
                )

                # The guarantee, checked before the call rather than asserted
                # in a docstring. Rendered without the summary; see the module
                # docstring for why that is the strict form of the check.
                if enforce and prior_chapters:
                    assert_no_prior_prose(
                        chapter_context.render(include_summary=False),
                        prior_chapters,
                        canon=bible_context + "\n" + chapter_context.plan_block,
                        window=leak_window,
                    )

                completion = context.call(
                    role=context.spec.agent,
                    system=context.agent.system(
                        tone=context.config.get("novel.tone"),
                        number=plan.number,
                        title=plan.title,
                        target_words=bands["words_target"],
                        untrusted_clause=UNTRUSTED_CLAUSE),
                    prompt=chapter_context.render(),
                    task={
                        "kind": "chapter",
                        "chapter": plan.number,
                        "iteration": iteration,
                        "title": plan.title,
                        "target_words": bands["words_target"],
                        "names": names,
                        "sentences_per_paragraph":
                            context.config.get("novel.sentences_per_paragraph.max") - 2,
                    },
                    chapter=plan.number,
                    iteration=iteration,
                )
                usage = completion.usage if usage is None else usage + completion.usage
                draft = completion.text

                verdicts = {
                    critic.name: critic.review(CriticContext(
                        chapter=plan.number, text=draft, characters=cast,
                        world_rules=rules, config=bands, plan=plan,
                    ))
                    for critic in critics
                }
                for name, verdict in verdicts.items():
                    history[name].append(verdict)
                scores = {name: v.score for name, v in verdicts.items()}
                decision = GateDecision(
                    chapter=plan.number, iteration=iteration, scores=scores,
                    threshold=gate.threshold, aggregate=gate.aggregate,
                    verdict="accept",
                )
                passed = decision.score >= gate.threshold

                if best is None or decision.score > best[0]:
                    best = (decision.score, draft, verdicts)

                if passed:
                    decision = GateDecision(plan.number, iteration, scores, gate.threshold,
                                            gate.aggregate, "accept")
                elif iteration < gate.max_iterations:
                    decision = GateDecision(plan.number, iteration, scores, gate.threshold,
                                            gate.aggregate, "retry")
                else:
                    decision = GateDecision(plan.number, iteration, scores, gate.threshold,
                                            gate.aggregate, context.spec.on_fail)

                decisions.append(decision)
                # The gate's own record. Without it the log says which calls
                # happened but not why a chapter was accepted, and "show me
                # what the agents did" stops one question short.
                context.log({"event": "gate_decision", "flow_id": context.spec.id,
                             **decision.to_dict()})
                context.report(
                    f"    ch{plan.number:02d} draft {iteration}: "
                    + ", ".join(f"{k} {v}/10" for k, v in sorted(scores.items()))
                    + f" -> {decision.verdict}"
                )
                for critic_name, verdict in sorted(verdicts.items()):
                    for finding in verdict.findings:
                        context.report(
                            f"      [{critic_name}] {finding.kind}: {finding.quote!r}"
                        )

                if passed:
                    record = self._store(context, plan, draft, verdicts, iteration,
                                         bands, "approved", artefacts,
                                         history=history)
                    prior_chapters.append(draft)
                    break

                findings = tuple(f for v in verdicts.values() for f in v.findings)

                if iteration == gate.max_iterations:
                    if context.spec.on_fail == "halt":
                        raise GateHalted(
                            f"chapter {plan.number} never reached {gate.threshold}/10 "
                            f"in {gate.max_iterations} drafts (best {best[0]}/10); "
                            f"FLOW-4 on_fail=halt"
                        )
                    # Keep the best draft, not the last.
                    score, draft, verdicts = best
                    warnings = tuple(
                        f"{f.kind}: {f.quote}"
                        for v in verdicts.values() for f in v.findings
                    )
                    record = self._store(context, plan, draft, verdicts, iteration,
                                         bands, "accepted_with_warnings", artefacts,
                                         warnings=warnings, history=history)
                    prior_chapters.append(draft)
                    context.report(
                        f"    ch{plan.number:02d} accepted with warnings "
                        f"(best draft scored {score}/10)"
                    )

            assert record is not None
            records.append(record)
            summaries.append(self._summarise(context, plan, prior_chapters[-1], artefacts))

        approved = sum(1 for r in records if r.status == "approved")
        context.report(
            f"    {approved}/{len(records)} chapters approved, "
            f"{len(records) - approved} accepted with warnings"
        )
        return StageResult(
            artefacts=tuple(artefacts),
            usage=usage,
            data={"chapters": tuple(records), "decisions": tuple(decisions)},
        )

    # -- resume ----------------------------------------------------------

    @staticmethod
    def _already_done(context) -> dict[int, dict]:
        """Chapter records from a previous run, by number.

        Only chapters the previous run actually finished count. A chapter left
        ``pending`` is rewritten, which is what makes the documented repair -
        delete the file, reset the status - do what it says.
        """
        state = getattr(context, "state", None)
        rows = getattr(state, "chapters", None) or []
        return {
            int(r["number"]): r for r in rows
            if r.get("status") in ("approved", "accepted_with_warnings")
        }

    def _reuse(self, context, plan, done, bands, artefacts):
        row = done.get(plan.number)
        if row is None:
            return None
        chapter_path = f"chapters/ch{plan.number:02d}.md"
        summary_path = f"chapters/ch{plan.number:02d}.summary.md"
        if not context.workspace.exists(chapter_path):
            return None  # state says done, disk disagrees; disk wins

        text = context.workspace.read_text(chapter_path)
        summary = (context.workspace.read_text(summary_path)
                   if context.workspace.exists(summary_path) else "")
        artefacts.append(chapter_path)
        if summary:
            artefacts.append(summary_path)
        return ChapterRecord.from_dict(row), text, summary

    # -- persistence -----------------------------------------------------

    def _store(self, context, plan, draft, verdicts, iteration, bands, status,
               artefacts, *, warnings=(), history=None):
        path = f"chapters/ch{plan.number:02d}.md"
        context.workspace.write_text(path, content=draft.rstrip() + "\n")
        artefacts.append(path)

        for name, verdict in sorted(verdicts.items()):
            critique_path = f"critiques/ch{plan.number:02d}.{name}.json"
            drafts = (history or {}).get(name) or [verdict]
            context.workspace.write_json(critique_path, data={
                "chapter": plan.number,
                "critic": name,
                "drafts": len(drafts),
                # Every draft this critic saw, in order. iterations[0] is
                # the first attempt, findings and all.
                "iterations": [v.to_dict() for v in drafts],
                "final": verdict.to_dict(),
            })
            artefacts.append(critique_path)

        body = chapter_body(draft)
        width = bands["chars_per_line_max"]
        lines = sum(len(wrap_paragraph(" ".join(p.split()), width)) for p in paragraphs(body))
        return ChapterRecord(
            number=plan.number, status=status, words=count_words(body), lines=lines,
            iterations=iteration, scores={k: v.score for k, v in verdicts.items()},
            warnings=warnings,
        )

    def _summarise(self, context, plan, draft, artefacts) -> str:
        completion = context.call(
            role=context.spec.agent,
            system="Summarise the chapter in two sentences, extractively.",
            prompt="(summary)",
            task={"kind": "summary", "chapter": plan.number, "text": draft},
            chapter=plan.number,
        )
        path = f"chapters/ch{plan.number:02d}.summary.md"
        context.workspace.write_text(path, content=completion.text.strip() + "\n")
        artefacts.append(path)
        return completion.text
