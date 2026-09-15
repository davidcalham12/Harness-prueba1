"""Executing the spec.

This module contains **no stage order and no threshold**. It loads
``specs/flow.yaml``, walks the stages it finds there in the order it finds
them, looks each one's ``impl`` up in :mod:`novaforge.stages`, and runs it.
Reorder the YAML and this file runs the new order without being edited.

What it does own is everything that is true of *every* stage: narrowing the
Bible to the authority the spec grants, counting calls and tokens, recording
one audit row per call, persisting state after each stage so a crashed run
resumes, and applying the ``on_fail`` policy.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .agents import AgentRegistry, load_agents
from .bible import FileBible, ReadOnlyBible
from .config import Config
from .domain.models import Usage
from .engines.base import Completion, Engine, Request
from .pricing import cost_usd
from .security.audit import (
    AuditChain,
    Budget,
    BudgetExceeded,
    BudgetGuard,
    ChainReport,
)
from .security.prompting import scan_for_injection
from .security.secrets import Redactor
from .security.sandbox import Workspace
from .spec.flow import FlowSpec, Stage as StageSpec
from .stages import build_stage
from .textops import slugify

__all__ = ["BudgetExceeded", "Orchestrator", "RunState", "StageFailed"]


class StageFailed(RuntimeError):
    """A stage raised and its ``on_fail`` policy is ``halt``."""


@dataclass
class RunState:
    """What survives a crash. Written after every stage."""

    slug: str
    premise: str
    config_hash: str
    stage: str = "pending"
    completed_stages: list[str] = field(default_factory=list)
    chapters: list[dict[str, Any]] = field(default_factory=list)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "premise": self.premise,
            "config_hash": self.config_hash,
            "stage": self.stage,
            "completed_stages": list(self.completed_stages),
            "chapters": list(self.chapters),
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunState":
        state = cls(
            slug=str(data["slug"]),
            premise=str(data.get("premise", "")),
            config_hash=str(data.get("config_hash", "")),
            stage=str(data.get("stage", "pending")),
        )
        state.completed_stages = list(data.get("completed_stages", []))
        state.chapters = list(data.get("chapters", []))
        state.calls = int(data.get("calls", 0))
        state.input_tokens = int(data.get("input_tokens", 0))
        state.output_tokens = int(data.get("output_tokens", 0))
        state.cost_usd = float(data.get("cost_usd", 0.0))
        state.notes = list(data.get("notes", []))
        return state


class Orchestrator:
    """Runs a flow spec against a workspace."""

    def __init__(
        self,
        *,
        spec: FlowSpec,
        config: Config,
        workspace: Workspace,
        engine: Engine,
        premise: str,
        slug: str,
        report: Callable[[str], None] = print,
        agents: AgentRegistry | None = None,
    ) -> None:
        self.spec = spec
        self.config = config
        self.workspace = workspace
        self.engine = engine
        self.premise = premise
        self.slug = slug
        # SEC-2.2. Everything this run writes or prints goes through the
        # redactor: logs, state.json and the terminal all get copied into
        # tickets by someone quoting a traceback in a hurry.
        self.redactor = Redactor.from_env()
        self.report = lambda line: report(self.redactor.scrub(str(line)))
        self._injection_hits = 0
        self._bible = FileBible(workspace, on_write=self._on_bible_write)
        self.state = RunState(slug=slug, premise=premise, config_hash=config.hash)
        # Agents are data too. Loading here rather than in each stage means a
        # missing or contradictory skill stops the run before the first call,
        # not three stages in.
        self.agents = agents if agents is not None else load_agents()
        self.agents.check_against_flow(spec)
        self._chain = AuditChain(workspace)
        self._budget = BudgetGuard(Budget.from_config(config))

    # -- audit -----------------------------------------------------------

    def _on_bible_write(self, role: str, section: str, size: int, findings) -> None:
        """Injection attempts in the canon are logged, never deleted (SEC-4.5)."""
        if findings:
            self._injection_hits += len(findings)
            for hit in findings:
                self.report(
                    f"    note: injection-shaped text in bible/{section}.md "
                    f"[{hit['kind']}] {hit['quote']!r} — logged, not removed"
                )
        self._log({
            "event": "bible_write",
            "role": role,
            "section": section,
            "bytes": size,
            "injection_findings": list(findings),
        })

    def _log(self, row: Mapping[str, Any]) -> None:
        """One chained row. Every write to the audit log goes through here."""
        self._chain.append(self.redactor.scrub_data(
            {"ts": round(time.time(), 3), "config_hash": self.config.hash, **row}))

    # -- the model call, in one place ------------------------------------

    def _call(self, *, role: str, system: str, prompt: str, task: Mapping[str, Any],
              chapter: int | None = None, iteration: int | None = None) -> Completion:
        """Every model call in the run goes through here.

        Which is what makes the audit row unavoidable rather than something
        each stage has to remember, and what will make the budget guard a
        single check when it lands.
        """
        # SEC-6.1: before the call, not after. Discovering the overrun
        # afterwards is discovering it too late.
        self._budget.check()
        request = Request(role=role, system=system, prompt=prompt, task=dict(task))
        started = time.time()
        completion = self.engine.complete(request)

        self.state.calls += 1
        self.state.input_tokens += completion.usage.input_tokens
        self.state.output_tokens += completion.usage.output_tokens
        spent = cost_usd(completion.model, completion.usage.input_tokens,
                         completion.usage.output_tokens)
        self.state.cost_usd += spent
        self._budget.record(cost_usd=spent,
                            input_tokens=completion.usage.input_tokens,
                            output_tokens=completion.usage.output_tokens)

        hits = scan_for_injection(completion.text)
        if hits:
            self._injection_hits += len(hits)

        self._log({
            "event": "call",
            "flow_id": self._current_stage_id,
            "role": role,
            "kind": request.kind,
            "chapter": chapter,
            "iteration": iteration,
            "model": completion.model,
            "input_tokens": completion.usage.input_tokens,
            "output_tokens": completion.usage.output_tokens,
            "cost_usd": cost_usd(completion.model, completion.usage.input_tokens,
                                 completion.usage.output_tokens),
            "elapsed_s": round(time.time() - started, 4),
            "injection_findings": hits,
        })
        return completion

    _current_stage_id = "-"

    # -- the run ---------------------------------------------------------

    def run(self, *, resume: bool = False) -> RunState:
        if resume and self.workspace.exists("state.json"):
            self.state = RunState.from_dict(self.workspace.read_json("state.json"))
            if self.state.config_hash != self.config.hash:
                raise StageFailed(
                    f"cannot resume: state.json was written with config "
                    f"{self.state.config_hash}, this run is {self.config.hash}. "
                    f"A resumed run must be the same novel."
                )
            self._budget = BudgetGuard.resumed(Budget.from_config(self.config), self.state)

        self.workspace.write_json("config.snapshot.json", data={
            "config_hash": self.config.hash,
            "layers": list(self.config.sources),
            "resolved": self.config.data,
        })
        if self.spec.substitutions:
            self._log({"event": "spec_substitution",
                       "substitutions": list(self.spec.substitutions)})

        outline = None
        total = len(self.spec)

        for index, stage_spec in enumerate(self.spec, start=1):
            self._current_stage_id = stage_spec.id
            label = (f"  [{index}/{total}] {stage_spec.id} {stage_spec.name} "
                     f"-> {stage_spec.agent}")

            if stage_spec.id in self.state.completed_stages:
                self.report(label + "   (already done, skipped)")
                if stage_spec.impl == "outline" and self.workspace.exists("outline.md"):
                    outline = self._rebuild_outline()
                continue

            self.report(label)
            self.state.stage = stage_spec.id

            context = self._context_for(stage_spec, outline)
            try:
                result = build_stage(stage_spec.impl).run(context)
            except BudgetExceeded as exc:
                # Not a stage failure: the run did what it was told and hit a
                # ceiling. State is saved and the chain is closed, so `resume`
                # continues from here once the ceiling is raised (SEC-6.1).
                self._log({"event": "budget_exceeded", "flow_id": stage_spec.id,
                           "message": str(exc), "spent": self._budget.summary()})
                self._persist()
                self._write_cost()
                self.report(f"    stopped: {exc}")
                self.report(f"    spent {self._budget.summary()}")
                self.report(f"    resume with: novaforge resume {self.slug}")
                raise
            except Exception as exc:
                self._log({"event": "stage_failed", "flow_id": stage_spec.id,
                           "error": type(exc).__name__, "message": str(exc)})
                if stage_spec.on_fail == "skip":
                    self.report(f"    stage failed ({exc}); on_fail=skip, continuing")
                    self.state.notes.append(f"{stage_spec.id} skipped: {exc}")
                    self._persist()
                    continue
                self._persist()
                raise StageFailed(f"{stage_spec.id} ({stage_spec.name}): {exc}") from exc

            if result.data.get("outline") is not None:
                outline = result.data["outline"]
            if result.data.get("chapters"):
                self.state.chapters = [r.to_dict() for r in result.data["chapters"]]
            for note in result.notes:
                # A resumed run re-runs stages; the same note arriving twice
                # is the same fact, not two facts.
                if note not in self.state.notes:
                    self.state.notes.append(note)
            self.state.completed_stages.append(stage_spec.id)
            self._log({"event": "stage_complete", "flow_id": stage_spec.id,
                       "artefacts": list(result.artefacts)})
            self._persist()

        self.state.stage = "complete"
        self._persist()
        self._write_cost()
        return self.state

    def _context_for(self, stage_spec: StageSpec, outline):
        from .stages.base import StageContext

        # SEC-4.4 in one line: a stage the spec does not declare `writes_bible`
        # is handed an object with no `write` method at all.
        bible = self._bible if stage_spec.writes_bible else ReadOnlyBible(self._bible)
        return StageContext(
            spec=stage_spec,
            agent=self.agents.get(stage_spec.agent),
            config=self.config,
            workspace=self.workspace,
            bible=bible,
            engine=self.engine,
            premise=self.premise,
            report=self.report,
            call=self._call,
            log=self._log,
            outline=outline,
            state=self.state,
        )

    def _rebuild_outline(self):
        from .domain.models import ChapterPlan, Outline
        from .textops import parse_outline

        rows = parse_outline(self.workspace.read_text("outline.md"))
        return Outline(plans=tuple(
            ChapterPlan(number=int(r["number"]), title=str(r["title"]), pov=str(r["pov"]),
                        tension=int(r["tension"]), promise=str(r["promise"]),
                        beats=tuple(str(b) for b in r["beats"]))
            for r in rows
        ))

    def _persist(self) -> None:
        self.workspace.write_json(
            "state.json", data=self.redactor.scrub_data(self.state.to_dict()))

    def _write_cost(self) -> None:
        self.workspace.write_json("logs/cost.json", data={
            "model": self.engine.model,
            "calls": self.state.calls,
            "input_tokens": self.state.input_tokens,
            "output_tokens": self.state.output_tokens,
            "total_tokens": self.state.input_tokens + self.state.output_tokens,
            "cost_usd": round(self.state.cost_usd, 6),
            "injection_findings": self._injection_hits,
            "budget": {
                "max_cost_usd": self._budget.budget.max_cost_usd,
                "max_calls": self._budget.budget.max_calls,
                "max_tokens": self._budget.budget.max_tokens,
                "remaining": self._budget.remaining,
            },
        })

    def verify_chain(self) -> ChainReport:
        """Recompute the audit chain. Tamper-evident, not tamper-proof."""
        return self._chain.verify()


def derive_slug(premise: str) -> str:
    return slugify(premise)


def generated_paths(spec: FlowSpec) -> tuple[str, ...]:
    """Everything a run writes, derived from the spec's declared outputs.

    Spec-driven rather than a hardcoded list: a stage that starts writing
    somewhere new declares it in ``specs/flow.yaml``, and this follows without
    being edited. Patterns like ``chapters/ch{n:02d}.md`` contribute their
    directory, since the whole directory belongs to the run.
    """
    paths: set[str] = {"state.json", "config.snapshot.json", "outline.md",
                       "synopsis.md", "logs", "bible", "chapters", "critiques", "dist"}
    for stage in spec.stages:
        for output in stage.outputs:
            head = output.split("/")[0]
            paths.add(head if "/" in output else output)
    return tuple(sorted(paths))


def reset_run(workspace: Workspace, spec: FlowSpec) -> tuple[str, ...]:
    """Delete a previous run's artefacts, leaving anything else alone.

    Needed because the audit log is append-only: without this, a second ``new``
    into the same slug would produce a log describing two runs as though they
    were one, and a shorter novel would publish the leftover chapters of a
    longer one. Files the run does not generate - ``output/golden-tiny/README.md``,
    for instance - are untouched.
    """
    import shutil

    removed: list[str] = []
    for name in generated_paths(spec):
        target = workspace.resolve(name)
        if not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        removed.append(name)
    return tuple(removed)
