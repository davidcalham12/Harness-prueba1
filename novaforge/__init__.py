"""NovaForge - a spec-driven multi-agent harness for science-fiction novels.

The pipeline is defined in ``specs/flow.yaml`` and executed by
:mod:`novaforge.orchestrator`; the agents are defined by their ``SKILL.md``
files under ``.claude/skills/`` and their specs under ``specs/agents/``. No
stage order, gate threshold or prompt lives in this package's source.

Those three are checkable rather than aspirational. ``tools/check_specs.py``
fails if a stage names an agent with no skill, if a skill contradicts its spec,
or if a declared requirement has no test citing it; and
``tests/test_agents.py`` asserts that no stage module contains a prompt.

Start at :func:`novaforge.composition.build_run`, which is the only place
concrete classes are wired together. :mod:`novaforge.cli` parses flags and
turns exceptions into exit codes; it constructs nothing, so a caller that is
not a command line can start a run without going through ``argparse``.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__", "main"]


def main(argv=None) -> int:
    """Console entry point. Imported lazily so ``import novaforge`` stays cheap."""
    from .cli import main as _main

    return _main(argv)
