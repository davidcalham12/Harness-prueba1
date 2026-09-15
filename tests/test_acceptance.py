"""The acceptance criteria from `specs/acceptance.md`, one test each.

These overlap with the unit suites on purpose. The other modules test parts;
this one tests the claims a reader is asked to believe, at the level they are
stated — so if a criterion stops holding, the failure names the criterion
rather than an implementation detail three layers down.

`tools/check_specs.py` fails if any ACC identifier has no test here.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from conftest import PREMISE, run_novel


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    lines: list[str] = []
    orch, state, space = run_novel(tmp_path_factory.mktemp("acc"), report=lines.append)
    return orch, state, space, lines


def test_acc_1_the_pipeline_runs_end_to_end_offline(run, flow):
    """ACC-1 — six stages in the order the spec declares them, exit 0, both
    artefacts written, no network and no credential."""
    _, state, space, _ = run
    assert state.stage == "complete"
    assert state.completed_stages == [s.id for s in flow]
    assert space.exists("dist/book.md") and space.exists("dist/book.pdf")


def test_acc_1_runs_with_no_third_party_imports(run):
    """ACC-1 — no dependency outside the standard library."""
    import novaforge
    import pkgutil

    stdlib = set(sys.stdlib_module_names)
    allowed = stdlib | {"novaforge"}
    for module in pkgutil.walk_packages(novaforge.__path__, "novaforge."):
        source = __import__(module.name, fromlist=["_"])
        for name in getattr(source, "__dict__", {}).values():
            root = getattr(name, "__module__", "") or ""
            assert root.split(".")[0] in allowed or not root, root


def test_acc_2_the_gate_rejects_and_the_rewrite_repairs(run):
    """ACC-2 — at least one chapter is rejected and redrafted. A run where
    everything passes first time demonstrates nothing about the gate."""
    _, state, _, lines = run
    report = "\n".join(lines)
    assert "-> retry" in report
    rejected = [c for c in state.chapters if c["iterations"] > 1]
    assert rejected, "no chapter was ever redrafted"
    assert all(c["status"] == "approved" for c in rejected)


def test_acc_3_the_rejected_drafts_verdict_survives(run):
    """ACC-3 — iterations[0] holds the name-drift finding quoting the drifted
    surname; final.findings is empty."""
    _, _, space, _ = run
    critique = space.read_json("critiques/ch02.continuity.json")
    first = critique["iterations"][0]
    assert first["findings"][0]["kind"] == "name-drift"
    assert first["findings"][0]["quote"]
    assert critique["final"]["findings"] == []


def test_acc_4_the_writer_never_receives_prior_prose(run, config):
    """ACC-4 — enforced at runtime, so a completed run is the evidence; the
    guard's failure path is proven directly here."""
    from novaforge.context import ContextPolicyViolation, assert_no_prior_prose

    _, state, space, _ = run
    assert state.stage == "complete"
    window = config.get("context.leak_window_words")
    chapter = space.read_text("chapters/ch01.md")
    stolen = " ".join(chapter.split()[5:5 + window + 5])
    with pytest.raises(ContextPolicyViolation):
        assert_no_prior_prose(stolen, [chapter], window=window)


def test_acc_4_the_canon_exemption_is_necessary(run):
    """ACC-4 — without it, a chapter quoting a world rule would make that rule
    unquotable for every later chapter."""
    from novaforge.context import assert_no_prior_prose

    _, _, space, _ = run
    rule = " ".join(space.read_text("bible/world.md").split()[10:25])
    assert_no_prior_prose(rule, [f"# T\n{rule}"], canon=rule)


def test_acc_5_every_chapter_is_inside_the_configured_band(run, config):
    """ACC-5 — length is measured, not asserted. A draft outside the band is
    sent back regardless of how good it is."""
    _, state, _, _ = run
    low = config.get("novel.words_per_chapter.min")
    high = config.get("novel.words_per_chapter.max")
    for chapter in state.chapters:
        assert low <= chapter["words"] <= high, chapter


def test_acc_6_two_runs_of_the_same_command_agree(tmp_path):
    """ACC-6 — reproducible. Checked across two separate runs rather than by
    reusing one, which would prove only that a file can be read twice."""
    _, _, first = run_novel(tmp_path / "a", slug="r")
    _, _, second = run_novel(tmp_path / "b", slug="r")
    for name in ("bible/world.md", "outline.md", "chapters/ch02.md", "dist/book.md"):
        assert first.read_text(name) == second.read_text(name), name
    assert first.read_bytes("dist/book.pdf") == second.read_bytes("dist/book.pdf")


def test_acc_6_reproducibility_survives_a_fresh_interpreter():
    """ACC-6 — 'on separate machines' starts with 'in a separate process'.
    Seeding from hash() passes every in-process check and fails this one."""
    code = (
        "from novaforge.engines import build_engine;"
        "from novaforge.engines.base import Request;"
        "e=build_engine('mock',model='claude-opus-5',seed=0);"
        "print(e.complete(Request(role='r',system='s',prompt='p',"
        "task={'kind':'characters','characters':4})).text[:120])"
    )
    outputs = {subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, check=True).stdout for _ in range(2)}
    assert len(outputs) == 1


def test_acc_7_resume_rewrites_only_what_is_missing(tmp_path):
    """ACC-7 — one lost chapter costs one chapter to repair. Only the call
    count distinguishes this from a resume that re-ran everything."""
    from test_resume import break_chapter_three

    _, state, space = run_novel(tmp_path, slug="acc7")
    before = state.calls
    break_chapter_three(space)
    lines: list[str] = []
    _, resumed, _ = run_novel(tmp_path, slug="acc7", resume=True, report=lines.append)
    report = "\n".join(lines)
    assert "ch01 already approved, reused" in report
    assert "ch03 draft 1" in report
    assert resumed.calls - before == 6
    assert resumed.stage == "complete"


def test_acc_7_resume_recovers_its_config_from_the_snapshot(tmp_path):
    """ACC-7 — forgetting --profile tiny cannot continue a three-chapter book
    as a twelve-chapter one. Driven through the CLI, because the flag being
    forgotten is a CLI flag."""
    from conftest import isolated_root
    from novaforge import cli

    root = isolated_root(tmp_path)
    original = cli.package_root
    cli.package_root = lambda: root
    try:
        assert cli.main(["new", PREMISE, "--slug", "acc7b", "--profile", "tiny",
                         "--engine", "mock", "--quiet"]) == 0
        # No --profile this time.
        assert cli.main(["resume", "acc7b", "--quiet"]) == 0
    finally:
        cli.package_root = original

    state = json.loads((root / "output" / "acc7b" / "state.json").read_text("utf-8"))
    assert len(state["chapters"]) == 3


def test_acc_8_the_run_can_be_reconstructed(run, config):
    """ACC-8 — one row per call naming its flow_id and config_hash, plus
    gate_decision and bible_write rows."""
    _, state, space, _ = run
    rows = [json.loads(line) for line in space.read_lines("logs/agents.jsonl")]
    calls = [r for r in rows if r["event"] == "call"]
    assert len(calls) == state.calls
    assert all(r["config_hash"] == config.hash for r in rows)
    assert all(r["flow_id"] for r in calls)
    assert [r["event"] for r in rows].count("gate_decision") >= len(state.chapters)
    assert [r["event"] for r in rows].count("bible_write") == 4


def test_acc_8_the_chain_detects_an_edit(run):
    """ACC-8 — tamper-evident. The limit is stated in SEC-6 and tested there."""
    from novaforge.security.audit import AuditChain

    orch, _, space, _ = run
    assert orch.verify_chain().intact
    rows = [json.loads(line) for line in space.read_lines("logs/agents.jsonl")]
    rows[3]["cost_usd"] = 0.0
    (space.root / "logs" / "agents.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")
    assert not AuditChain(space).verify().intact


def test_acc_9_a_ceiling_stops_the_run_and_leaves_it_resumable(tmp_path):
    """ACC-9 — spend is bounded before it happens, not reported afterwards."""
    from novaforge.security.audit import BudgetExceeded

    with pytest.raises(BudgetExceeded):
        run_novel(tmp_path, slug="acc9", overrides={"budget": {"max_calls": 5}})
    state = json.loads((tmp_path / "acc9" / "state.json").read_text("utf-8"))
    assert state["calls"] == 5           # stopped at the ceiling, not past it
    assert state["stage"] != "complete"
    assert state["completed_stages"]     # progress kept, so it can resume


def test_acc_10_no_structure_numbers_or_prompts_live_in_the_python():
    """ACC-10 — the three claims in novaforge/__init__.py, checked."""
    import inspect

    from novaforge import orchestrator
    from novaforge.stages import bible_sections, chapters, outline, publish, style

    assert "FLOW-1" not in inspect.getsource(orchestrator)
    assert "threshold=8" not in inspect.getsource(chapters)
    for module in (bible_sections, chapters, outline, publish, style):
        assert "You are the" not in inspect.getsource(module), module.__name__


def test_acc_10_the_spec_checker_passes():
    """ACC-10 — and the checker that enforces it actually runs clean."""
    from novaforge.config import package_root

    result = subprocess.run(
        [sys.executable, str(package_root() / "tools" / "check_specs.py")],
        capture_output=True, text=True, cwd=str(package_root()))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all traced" in result.stdout


def test_acc_11_the_stated_limits_are_the_real_ones():
    """ACC-11 — what is *not* claimed. If one of these starts being false, the
    acceptance criteria are covering more than they say and ACC-11 needs
    updating."""
    import inspect

    from novaforge.agents import load_agents
    from novaforge.config import package_root
    from novaforge.engines import EngineError, build_engine
    from novaforge.export import markdown, pdf

    with pytest.raises(EngineError, match="not implemented"):
        build_engine("anthropic", model="claude-opus-5")

    parked = {a.name for a in load_agents(package_root()) if not a.on_shipping_path}
    assert parked == {"continuity_critic", "science_critic"}

    for module in (markdown, pdf):
        assert "Redactor" not in inspect.getsource(module)


def test_cfg_10_7_a_profile_change_alone_writes_a_different_novel(tmp_path):
    """CFG-10 and CFG-10.7 — the same code, a different novel. No Python is
    edited between the two runs and no argument other than the profile
    changes. If a length could only be altered by editing a module, every one
    of those numbers would be a code review instead of a setting."""
    _, tiny, tiny_space = run_novel(tmp_path / "t", slug="n", profile="tiny")
    _, small, small_space = run_novel(tmp_path / "s", slug="n", profile="small")

    assert len(tiny.chapters) == 3 and len(small.chapters) == 8
    assert all(300 <= c["words"] <= 550 for c in tiny.chapters)
    assert all(900 <= c["words"] <= 1400 for c in small.chapters)
    assert tiny_space.read_json("config.snapshot.json")["config_hash"] != \
        small_space.read_json("config.snapshot.json")["config_hash"]


def test_acc_11_the_mock_ignores_the_premise(tmp_path):
    """ACC-11 — the limitation a reader is most likely to miss, pinned.

    Two opposite premises produce byte-identical canon, outline and chapters.
    Only world.md and the synopsis differ, and only because they quote the
    premise verbatim in one line each.

    This is asserted rather than merely documented because it was found by
    reading the output and noticing, which is the worst way for a limitation to
    surface. If the mock ever becomes premise-sensitive, this test fails and
    tells whoever changed it to update ACC-11, the README and the fixture's own
    README - all of which currently promise the opposite.
    """
    _, _, spacefic = run_novel(tmp_path / "a", slug="p",
                               premise="A deep-space salvage crew finds a derelict")
    _, _, forge = run_novel(tmp_path / "b", slug="p",
                            premise="A medieval blacksmith can reforge memories")

    for name in ("bible/characters.md", "bible/timeline.md", "bible/mysteries.md",
                 "outline.md", "chapters/ch01.md", "chapters/ch02.md"):
        assert spacefic.read_text(name) == forge.read_text(name), name

    # The two that do differ, differ only by the quoted premise.
    assert "blacksmith" in forge.read_text("bible/world.md")
    assert "blacksmith" not in forge.read_text("outline.md")


def test_acc_11_the_documentation_says_so_where_it_is_read(tmp_path):
    """ACC-11 — and it is said in the four places a reader actually looks, not
    only in this spec."""
    from novaforge.config import package_root

    root = package_root()
    for path, needle in (
        ("README.md", "ignores your premise"),
        ("RUNBOOK.md", "premise does not reach the prose"),
        ("output/golden-tiny/README.md", "nothing to do with the premise"),
        ("novaforge/engines/mock.py", "It ignores the premise"),
    ):
        # Read as prose: these documents are hard-wrapped, so the sentence
        # being looked for is split across lines, and in a blockquote each
        # of those lines starts with a "> " that would land mid-sentence.
        raw = (root / path).read_text(encoding="utf-8")
        prose = " ".join(re.sub(r"(?m)^\s*>\s?", "", raw).split())
        assert needle in prose, path
