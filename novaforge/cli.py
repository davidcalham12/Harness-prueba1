"""The command line.

Three commands: ``new`` starts a run, ``resume`` continues one, ``status``
reports on one without touching it.

The CLI's own job is small on purpose - parse flags into a config overlay, wire
the pieces together, print progress. Every number it accepts is a config key,
so ``--chapters 3`` and editing ``novel.chapters`` in JSON are the same change
arriving by different routes (CFG-4).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agents import AgentError, load_agents
from .config import Config, ConfigError, load_config, package_root
from .engines import EngineError, build_engine
from .orchestrator import (
    BudgetExceeded,
    Orchestrator,
    StageFailed,
    derive_slug,
    reset_run,
)
from .pricing import DEFAULT_MODEL, is_known_model
from .security.sandbox import SandboxViolation, Workspace
from .spec.flow import SpecError, load_flow

__all__ = ["main", "run_cli"]

_BANNER = "NovaForge"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novaforge",
        description="A spec-driven multi-agent harness for science-fiction novels.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="start a new novel")
    new.add_argument("premise", help="one sentence the novel grows from")
    new.add_argument("--profile", help="tiny | small | medium | full")
    new.add_argument("--config", dest="config_path", help="a partial config to overlay")
    new.add_argument("--slug", help="output directory name; derived from the premise if absent")
    new.add_argument("--engine", help="mock (free, deterministic) or anthropic")
    new.add_argument("--model", help="model id, e.g. claude-opus-5")
    new.add_argument("--chapters", type=int, help="overrides novel.chapters")
    new.add_argument("--words", type=int, dest="target_words",
                     help="overrides novel.words_per_chapter.target")
    new.add_argument("--wrap", type=int, help="overrides novel.chars_per_line.max")
    new.add_argument("--threshold", type=int, help="overrides quality_gate.threshold")
    new.add_argument("--max-revisions", type=int, help="overrides quality_gate.max_revisions")
    new.add_argument("--seed", type=int, help="overrides engine.seed")
    new.add_argument("--no-drift", action="store_true",
                     help="disable the mock's deliberate continuity error")
    new.add_argument("--max-cost-usd", type=float,
                     help="overrides budget.max_cost_usd")
    new.add_argument("--max-calls", type=int, help="overrides budget.max_calls")
    new.add_argument("--force", action="store_true",
                     help="discard an existing run in this slug and start over")
    new.add_argument("--quiet", action="store_true")

    resume = sub.add_parser("resume", help="continue an interrupted run")
    resume.add_argument("slug")
    resume.add_argument("--profile", help="must match the original run")
    resume.add_argument("--engine")
    resume.add_argument("--quiet", action="store_true")

    status = sub.add_parser("status", help="report on a run without changing it")
    status.add_argument("slug")

    return parser


def _overrides(args) -> dict:
    """Turn CLI flags into a config-shaped overlay.

    Only flags the user actually passed appear, so an absent flag inherits from
    the profile rather than overwriting it with a parser default.
    """
    novel, engine, gate, budget = {}, {}, {}, {}
    if getattr(args, "chapters", None) is not None:
        novel["chapters"] = args.chapters
    if getattr(args, "target_words", None) is not None:
        novel["words_per_chapter"] = {"target": args.target_words}
    if getattr(args, "wrap", None) is not None:
        novel["chars_per_line"] = {"max": args.wrap}
    if getattr(args, "engine", None):
        engine["name"] = args.engine
    if getattr(args, "model", None):
        engine["model"] = args.model
    if getattr(args, "seed", None) is not None:
        engine["seed"] = args.seed
    if getattr(args, "no_drift", False):
        engine["inject_drift"] = False
    if getattr(args, "threshold", None) is not None:
        gate["threshold"] = args.threshold
    if getattr(args, "max_revisions", None) is not None:
        gate["max_revisions"] = args.max_revisions
    if getattr(args, "max_cost_usd", None) is not None:
        budget["max_cost_usd"] = args.max_cost_usd
    if getattr(args, "max_calls", None) is not None:
        budget["max_calls"] = args.max_calls

    overlay = {}
    if novel:
        overlay["novel"] = novel
    if engine:
        overlay["engine"] = engine
    if gate:
        overlay["quality_gate"] = gate
    if budget:
        overlay["budget"] = budget
    return overlay


def _header(report, *, config, spec, engine, slug, out_dir, premise) -> None:
    title = premise.strip().rstrip(".")
    report(f"{_BANNER}: {title[:60]}  "
           f"[{config.get('novel.tone')}, {config.get('novel.chapters')} chapters]")
    report(f"  profile {config.get('profile') or 'none':<8} config {config.hash}")
    report(f"  spec    {spec.source}")
    report(f"  engine  {engine.name} / {engine.model}")
    report(f"  length  {config.get('novel.words_per_chapter.min')}-"
           f"{config.get('novel.words_per_chapter.max')} words per chapter, "
           f"wrapped at {config.get('novel.chars_per_line.max')}")
    report(f"  gate    {'+'.join(config.get('quality_gate.critics'))} >= "
           f"{config.get('quality_gate.threshold')}, "
           f"{config.get('quality_gate.max_revisions')} rewrites allowed, "
           f"on_fail={config.get('quality_gate.on_fail')}")
    report(f"  budget  ${config.get('budget.max_cost_usd'):,.2f}, "
           f"{config.get('budget.max_calls'):,} calls, "
           f"{config.get('budget.max_tokens'):,} tokens")
    report(f"  output  {out_dir}")
    report("")


def _summarise(report, state, workspace, orchestrator=None) -> None:
    report("")
    approved = sum(1 for c in state.chapters if c.get("status") == "approved")
    warned = len(state.chapters) - approved
    report(f"  chapters  {approved} approved"
           + (f", {warned} accepted with warnings" if warned else ""))
    report(f"  calls     {state.calls}  "
           f"({state.input_tokens:,} in / {state.output_tokens:,} out tokens)")
    report(f"  cost      ${state.cost_usd:,.4f}")
    if state.notes:
        report("  notes:")
        for note in state.notes:
            report(f"    - {note}")
    if orchestrator is not None:
        report(f"  audit     {orchestrator.verify_chain()}")
    report(f"  done. artefacts in {workspace.root / 'dist'}")


def _run(args, *, resume: bool) -> int:
    report = (lambda *_: None) if getattr(args, "quiet", False) else print
    root = package_root()

    if resume:
        # A resumed run must be the *same* novel, so the config is recovered
        # from the snapshot the original run wrote rather than rebuilt from
        # flags. Otherwise forgetting `--profile tiny` would silently ask to
        # continue a three-chapter book as a twelve-chapter one.
        snapshot_path = root / "output" / args.slug / "config.snapshot.json"
        if not snapshot_path.exists():
            print(f"no config snapshot at {snapshot_path}; cannot resume", file=sys.stderr)
            return 1
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        config = Config(snapshot["resolved"], sources=tuple(snapshot.get("layers", ())))
        if config.hash != snapshot.get("config_hash"):
            print(f"config snapshot is inconsistent with its own hash; refusing to resume",
                  file=sys.stderr)
            return 1
    else:
        try:
            config = load_config(
                profile=getattr(args, "profile", None),
                overlay_path=getattr(args, "config_path", None),
                overrides=_overrides(args),
                root=root,
            )
        except ConfigError as exc:
            print(f"config error: {exc}", file=sys.stderr)
            return 2

    model = config.get("engine.model")
    if not is_known_model(model):
        report(f"  note: {model!r} is not in the pricing table; "
               f"costs are estimated at the {DEFAULT_MODEL} tier")

    try:
        spec = load_flow(root / "specs" / "flow.yaml", config=config)
    except SpecError as exc:
        print(f"spec error: {exc}", file=sys.stderr)
        return 2

    engine_name = getattr(args, "engine", None) or config.get("engine.name")
    try:
        # Loaded before the workspace is touched: a contradictory skill should
        # stop the run before it creates a directory, not three stages in.
        agents = load_agents(root)
        agents.check_against_flow(spec)
    except AgentError as exc:
        print(f"agent error: {exc}", file=sys.stderr)
        print("run tools/check_specs.py for the full picture", file=sys.stderr)
        return 2

    try:
        engine = build_engine(
            engine_name,
            model=model,
            seed=config.get("engine.seed"),
            inject_drift=config.get("engine.inject_drift"),
        )
    except EngineError as exc:
        print(f"engine error: {exc}", file=sys.stderr)
        return 2

    premise = getattr(args, "premise", "")
    slug = getattr(args, "slug", None) or (args.slug if resume else None) or derive_slug(premise)
    out_dir = root / "output" / slug

    try:
        workspace = Workspace(out_dir)
    except SandboxViolation as exc:
        print(f"workspace error: {exc}", file=sys.stderr)
        return 2

    if resume:
        if not workspace.exists("state.json"):
            print(f"no run to resume at {out_dir}", file=sys.stderr)
            return 1
        premise = workspace.read_json("state.json").get("premise", "")
    elif workspace.exists("state.json"):
        # The audit log is append-only, so a second `new` into the same slug
        # would describe two runs as one. Overwriting is a deliberate act.
        if not getattr(args, "force", False):
            print(
                f"a run already exists at {out_dir}.\n"
                f"  continue it:  novaforge resume {slug}\n"
                f"  replace it:   novaforge new ... --slug {slug} --force",
                file=sys.stderr,
            )
            return 1
        removed = reset_run(workspace, spec)
        report(f"  replaced the previous run ({len(removed)} paths removed)")

    _header(report, config=config, spec=spec, engine=engine, slug=slug,
            out_dir=out_dir, premise=premise)

    orchestrator = Orchestrator(
        spec=spec, config=config, workspace=workspace, engine=engine,
        premise=premise, slug=slug, report=report, agents=agents,
    )
    try:
        state = orchestrator.run(resume=resume)
    except BudgetExceeded as exc:
        print(f"\nstopped on a budget ceiling: {exc}", file=sys.stderr)
        print(f"raise it in the config or with --max-cost-usd / --max-calls, "
              f"then: novaforge resume {slug}", file=sys.stderr)
        return 3
    except StageFailed as exc:
        print(f"\nrun halted: {exc}", file=sys.stderr)
        print(f"state saved; resume with: novaforge resume {slug}", file=sys.stderr)
        return 1

    _summarise(report, state, workspace, orchestrator)
    return 0


def _status(args) -> int:
    out_dir = package_root() / "output" / args.slug
    if not (out_dir / "state.json").exists():
        print(f"no run at {out_dir}", file=sys.stderr)
        return 1
    workspace = Workspace(out_dir, create=False)
    state = workspace.read_json("state.json")

    print(f"{_BANNER} status: {args.slug}")
    print(f"  stage       {state.get('stage')}")
    print(f"  config      {state.get('config_hash')}")
    print(f"  completed   {', '.join(state.get('completed_stages', [])) or 'none'}")
    print(f"  calls       {state.get('calls')}  "
          f"cost ${float(state.get('cost_usd', 0)):,.4f}")
    print("  chapters:")
    for chapter in state.get("chapters", []):
        scores = ", ".join(f"{k} {v}/10" for k, v in sorted(chapter.get("scores", {}).items()))
        print(f"    ch{chapter['number']:02d}  {chapter['status']:<24} "
              f"{chapter['words']:>5} words, {chapter['lines']:>3} lines, "
              f"{chapter['iterations']} draft(s)  [{scores}]")
        for warning in chapter.get("warnings", []):
            print(f"          warning: {warning}")
    for name in ("dist/book.md", "outline.md", "logs/agents.jsonl", "logs/cost.json"):
        mark = "yes" if workspace.exists(name) else "no "
        print(f"  {mark}  {name}")
    return 0


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "new":
        return _run(args, resume=False)
    if args.command == "resume":
        return _run(args, resume=True)
    if args.command == "status":
        return _status(args)
    return 2


def run_cli() -> None:  # pragma: no cover - console entry point
    raise SystemExit(main())
