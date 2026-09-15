#!/usr/bin/env python3
"""Check that the specs, the skills and the tests still agree.

Five kinds of drift this catches, none of which any test would:

1. **A stage naming an agent that does not exist.** ``specs/flow.yaml`` is data;
   nothing stops it naming ``chief_vibes_officer``. The run would fail at
   startup, but only when run.
2. **A requirement nobody tests.** Every ``AGT-XX-N``, ``CFG-n`` and ``ACC-n``
   declared under ``specs/`` must be cited by a test docstring. A spec
   requirement with no test is a promise the project is not keeping and does
   not know it.
3. **A skill contradicting its own spec.** The front matter in a ``SKILL.md``
   restates role, model and ``writes_bible``. If it drifts from the spec, one
   of the two documents is lying to a reader, and the ``writes_bible`` case is
   a security question (SEC-4.3).
4. **A test citing a requirement no spec declares.** The reverse of (2), and
   it catches a renumbered spec as surely as an invented identifier.
5. **A change record cited but never written.** ``CHG-nnn`` referenced from
   anywhere in the repository must exist in ``specs/changes/``. This is how
   `specs/acceptance.md` and `specs/CONFIG-SPEC.md` were missing for so long:
   cited confidently from several files, and nobody checked.

Exit status is 0 when everything traces and 1 otherwise, so this belongs in CI.

    python tools/check_specs.py [-v]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from novaforge.agents import AgentError, load_agents  # noqa: E402
from novaforge.spec.flow import load_flow  # noqa: E402

# Agent requirements, config rules and acceptance criteria. All three are
# declared in `specs/` and must be cited by a test docstring, so the tracing is
# one mechanism rather than three.
IDENTIFIER = re.compile(r"\b(?:AGT-[A-Z]{2,4}|CFG|ACC)-\d+(?:\.\d+)?\b")
SPEC_SOURCES = (
    "specs/agents/*.md",
    "specs/CONFIG-SPEC.md",
    "specs/acceptance.md",
)
FIELD = re.compile(r"^-\s+\*\*(?P<key>[a-z_]+):\*\*\s*(?P<value>.+?)\s*$", re.M)


class Report:
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self.problems: list[str] = []

    def ok(self, message: str) -> None:
        if self.verbose:
            print(f"  ok    {message}")

    def fail(self, message: str) -> None:
        self.problems.append(message)
        print(f"  FAIL  {message}")


def spec_fields(text: str) -> dict[str, str]:
    """The ``- **key:** value`` header block of an agent spec."""
    return {m.group("key"): m.group("value").strip().strip("`")
            for m in FIELD.finditer(text)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    report = Report(args.verbose)

    # -- load ------------------------------------------------------------
    try:
        flow = load_flow(ROOT / "specs" / "flow.yaml")
    except Exception as exc:
        print(f"  FAIL  specs/flow.yaml does not load: {exc}")
        return 1
    try:
        agents = load_agents(ROOT)
    except AgentError as exc:
        print(f"  FAIL  skills do not load: {exc}")
        return 1

    spec_dir = ROOT / "specs" / "agents"
    specs = {p.stem: p for p in sorted(spec_dir.glob("*.md"))}
    report.ok(f"{len(specs)} agent specs, {len(agents)} skills loaded")

    # -- 1. every stage's agent is defined, and every skill is reachable --
    for stage in flow.stages:
        if stage.agent in agents:
            report.ok(f"{stage.id} -> {stage.agent} has a skill")
        else:
            report.fail(f"{stage.id} names agent {stage.agent!r} with no "
                        f".claude/skills/{stage.agent}/SKILL.md")

    for agent in agents:
        if agent.name not in specs:
            report.fail(f"{agent.source} has no spec at "
                        f"specs/agents/{agent.name}.md")
        elif Path(agent.spec_path).name != f"{agent.name}.md":
            report.fail(f"{agent.source} points at {agent.spec_path!r}, "
                        f"not specs/agents/{agent.name}.md")
        else:
            report.ok(f"{agent.name} skill <-> spec")

    for name in specs:
        if name not in {a.name for a in agents}:
            report.fail(f"specs/agents/{name}.md has no "
                        f".claude/skills/{name}/SKILL.md")

    # -- 2. skills and specs agree -----------------------------------------
    for agent in agents:
        path = specs.get(agent.name)
        if path is None:
            continue
        fields = spec_fields(path.read_text(encoding="utf-8"))
        for key, actual in (("role", agent.role),
                            ("model", agent.model or ""),
                            ("writes_bible", str(agent.writes_bible).lower())):
            declared = fields.get(key, "")
            if declared != actual:
                report.fail(f"{agent.name}: spec says {key}={declared!r}, "
                            f"SKILL.md says {actual!r}")
            else:
                report.ok(f"{agent.name}.{key} agrees")

    # -- 3. authority matches the flow spec and the code -------------------
    try:
        agents.check_against_flow(flow)
        report.ok("Bible authority agrees across spec, skills and code (SEC-4.3)")
    except AgentError as exc:
        report.fail(str(exc))

    # -- 4. every requirement is cited by a test ---------------------------
    declared: dict[str, str] = {}
    for pattern in SPEC_SOURCES:
        for path in sorted(ROOT.glob(pattern)):
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            for identifier in IDENTIFIER.findall(path.read_text(encoding="utf-8")):
                declared[identifier] = rel

    cited: set[str] = set()
    for path in sorted((ROOT / "tests").rglob("*.py")):
        cited.update(IDENTIFIER.findall(path.read_text(encoding="utf-8")))

    for identifier, source in sorted(declared.items()):
        if identifier in cited:
            report.ok(f"{identifier} is traced to a test")
        else:
            report.fail(f"{identifier} ({source}) is not referenced by any test")

    for identifier in sorted(cited - set(declared)):
        report.fail(f"{identifier} is cited by a test but declared in no spec")

    # -- 4b. change records cited anywhere must exist ----------------------
    cited_changes: set[str] = set()
    change_ref = re.compile(r"\bCHG-\d{3}\b")
    for path in list(ROOT.rglob("*.py")) + list(ROOT.rglob("*.md")):
        if "output" in path.parts or "__pycache__" in path.parts:
            continue
        cited_changes.update(change_ref.findall(path.read_text(encoding="utf-8")))
    changes = {p.name.split("-")[0] + "-" + p.name.split("-")[1]
               for p in (ROOT / "specs" / "changes").glob("CHG-*.md")}
    for ref in sorted(cited_changes):
        if ref in changes:
            report.ok(f"{ref} has a change record")
        else:
            report.fail(f"{ref} is cited but specs/changes/ has no record for it")

    # -- 5. say which skills are not on the shipping path ------------------
    parked = [a.name for a in agents if not a.on_shipping_path]
    if parked:
        print(f"  note  {len(parked)} skill(s) declared off the shipping path: "
              f"{', '.join(parked)}")
        print("        their prompts are not sent by this build; the critics are "
              "scored in code")

    if report.problems:
        print(f"\nspecs FAILED: {len(report.problems)} problem(s)")
        return 1
    kinds = {"AGT": 0, "CFG": 0, "ACC": 0}
    for identifier in declared:
        kinds[identifier.split("-")[0]] += 1
    print(f"\nspecs OK: {len(specs)} agent specs, {len(agents)} skills, "
          f"{len(declared)} requirements "
          f"({kinds['AGT']} agent, {kinds['CFG']} config, {kinds['ACC']} acceptance), "
          f"all traced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
