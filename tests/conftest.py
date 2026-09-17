"""Shared fixtures.

Every fixture here builds a *real* object against a temporary directory rather
than a mock. The sandbox, the Bible and the orchestrator are the things under
test; replacing them with stubs would test the stubs.

The one thing that is substituted is the engine, and only because the mock
engine *is* the offline engine - it is production code, not a test double.
"""

from __future__ import annotations

import pytest

from novaforge.bible import FileBible
from novaforge.config import load_config, package_root
from novaforge.engines import build_engine
from novaforge.security.sandbox import Workspace
from novaforge.spec.flow import load_flow

PREMISE = "A deep-space salvage crew finds a derelict that remembers them"


@pytest.fixture
def repo_root():
    return package_root()


@pytest.fixture
def workspace(tmp_path):
    return Workspace(tmp_path / "run")


@pytest.fixture
def config():
    """The tiny profile - three short chapters, seconds, and $0 on the mock."""
    return load_config(profile="tiny")


@pytest.fixture
def flow(config):
    return load_flow(package_root() / "specs" / "flow.yaml", config=config)


@pytest.fixture
def engine(config):
    return build_engine(
        "mock",
        model=config.get("engine.model"),
        seed=config.get("engine.seed"),
        inject_drift=config.get("engine.inject_drift"),
    )


@pytest.fixture
def bible(workspace):
    return FileBible(workspace)


@pytest.fixture
def populated_bible(workspace, engine):
    """A Bible with all four sections written, as FLOW-1 and FLOW-2 leave it."""
    from novaforge.engines.base import Request

    book = FileBible(workspace)
    sections = {
        "world": {"kind": "world", "premise": PREMISE, "tone": "hard-scifi",
                  "rules": 4, "technology": 3, "factions": 2},
        "characters": {"kind": "characters", "characters": 4},
        "timeline": {"kind": "timeline", "rows": 6},
        "mysteries": {"kind": "mysteries", "mysteries": 3},
    }
    for section, task in sections.items():
        role = "worldbuilder" if section == "world" else "character_architect"
        text = engine.complete(Request(role=role, system="s", prompt="p", task=task)).text
        book.write(section, text, role=role)
    return book


def isolated_root(tmp_path):
    """A throwaway repo root, so a test never writes into the real ``output/``.

    ``config/``, ``specs/`` and ``.claude/`` are copied rather than faked:
    pointing the CLI at a different spec, or at invented prompts, would test a
    pipeline the project does not ship.
    """
    import shutil

    real = package_root()
    for name in ("config", "specs", ".claude"):
        shutil.copytree(real / name, tmp_path / name)
    (tmp_path / "output").mkdir(exist_ok=True)
    return tmp_path


def run_novel(tmp_path, *, slug="t", profile="tiny", overrides=None, resume=False,
              premise=PREMISE, sink=None, report=lambda *_: None):
    """Run the whole pipeline into ``tmp_path``. Used by the end-to-end tests."""
    from novaforge.orchestrator import Orchestrator

    cfg = load_config(profile=profile, overrides=overrides or {})
    spec = load_flow(package_root() / "specs" / "flow.yaml", config=cfg)
    space = Workspace(tmp_path / slug)
    eng = build_engine("mock", model=cfg.get("engine.model"), seed=cfg.get("engine.seed"),
                       inject_drift=cfg.get("engine.inject_drift"))
    orch = Orchestrator(spec=spec, config=cfg, workspace=space, engine=eng,
                        premise=premise, slug=slug, report=report, sink=sink)
    return orch, orch.run(resume=resume), space
