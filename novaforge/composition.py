"""The composition root - the one place concrete classes are wired together.

Every other module in this package names an interface and is handed an
implementation. This is where the implementations are chosen: which engine,
which spec, which agents, which workspace. Nothing else imports
:mod:`novaforge.engines.mock` or calls :func:`novaforge.agents.load_agents`,
which is what lets any of them be run in a test against something else.

Keeping it out of :mod:`novaforge.cli` matters for one practical reason. A CLI
is a place where flags are parsed and exit codes are chosen, and a caller that
is not a CLI - a test, a notebook, a web handler - should not have to go
through ``argparse`` and ``sys.exit`` to start a run. :func:`build_run` takes
values, returns an object, and raises on failure; ``cli.py`` turns those
exceptions into messages and numbers.

Every failure here is a distinct exception type, and that is deliberate: the
CLI maps them to different exit codes, and "the spec is malformed" and "the
budget ran out" are not the same thing to a script that wrapped this.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .agents import AgentRegistry, load_agents
from .config import Config, load_config, package_root
from .engines import build_engine
from .engines.base import Engine
from .orchestrator import Orchestrator, derive_slug
from .security.sandbox import Workspace
from .security.secrets import Redactor
from .security.validation import validate_premise, validate_slug
from .spec.flow import FlowSpec, load_flow

__all__ = ["Run", "build_run", "resolve_config"]


@dataclass(frozen=True)
class Run:
    """Everything a run needs, already wired.

    Exposed rather than hidden inside :class:`Orchestrator` so that a caller can
    inspect what was resolved - the config hash, the engine, the agent
    registry - and print or log it before anything is executed.
    """

    orchestrator: Orchestrator
    config: Config
    spec: FlowSpec
    engine: Engine
    agents: AgentRegistry
    workspace: Workspace
    slug: str
    premise: str

    @property
    def out_dir(self) -> Path:
        return self.workspace.root

    def execute(self, *, resume: bool = False):
        return self.orchestrator.run(resume=resume)


def resolve_config(
    *,
    profile: str | None = None,
    overlay_path: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    root: Path | None = None,
    resume_slug: str | None = None,
) -> Config:
    """The config for a run, built fresh or recovered from a snapshot.

    A resumed run must be the *same* novel, so its config comes from the
    snapshot the original wrote rather than from flags. Otherwise forgetting
    ``--profile tiny`` would silently ask to continue a three-chapter book as a
    twelve-chapter one.
    """
    base = root or package_root()
    if resume_slug is None:
        return load_config(profile=profile, overlay_path=overlay_path,
                           overrides=overrides, root=base)

    snapshot_path = base / "output" / resume_slug / "config.snapshot.json"
    if not snapshot_path.exists():
        raise FileNotFoundError(
            f"no config snapshot at {snapshot_path}; there is nothing to resume"
        )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    config = Config(snapshot["resolved"], sources=tuple(snapshot.get("layers", ())))
    if config.hash != snapshot.get("config_hash"):
        raise ValueError(
            f"config snapshot at {snapshot_path} does not match its own hash; "
            f"refusing to resume from a file that has been edited"
        )
    return config


def build_run(
    *,
    premise: str,
    config: Config,
    slug: str | None = None,
    engine_name: str | None = None,
    root: Path | None = None,
    report: Callable[[str], None] = print,
    validate: bool = True,
) -> Run:
    """Wire a run. Raises rather than returning a partly-built object.

    The order below is the order things can fail in, cheapest first: the spec
    and the agents are read before the workspace is created, so a contradictory
    skill stops the run before it leaves a directory behind.
    """
    base = root or package_root()

    spec = load_flow(base / "specs" / "flow.yaml", config=config)

    agents = load_agents(base)
    # SEC-4.3. Checked here, not inside the orchestrator, so that a caller
    # building a run to inspect it finds out immediately.
    agents.check_against_flow(spec)

    engine = build_engine(
        engine_name or config.get("engine.name"),
        model=config.get("engine.model"),
        seed=config.get("engine.seed"),
        inject_drift=config.get("engine.inject_drift"),
    )

    resolved_slug = slug or derive_slug(premise)
    if validate:
        # SEC-1, before the workspace exists. The slug is the only path
        # component in the whole program that comes from a human.
        resolved_slug = validate_slug(resolved_slug)
        premise = validate_premise(premise)

    workspace = Workspace(base / "output" / resolved_slug)

    orchestrator = Orchestrator(
        spec=spec,
        config=config,
        workspace=workspace,
        engine=engine,
        premise=premise,
        slug=resolved_slug,
        report=report,
        agents=agents,
    )
    return Run(
        orchestrator=orchestrator,
        config=config,
        spec=spec,
        engine=engine,
        agents=agents,
        workspace=workspace,
        slug=resolved_slug,
        premise=premise,
    )


def redactor_for_output() -> Redactor:
    """The redactor a caller should wrap its own printing in (SEC-2.2).

    Exposed here because a caller that prints a premise or a path is printing
    something user-supplied, and the orchestrator can only scrub what it emits
    itself.
    """
    return Redactor.from_env()
