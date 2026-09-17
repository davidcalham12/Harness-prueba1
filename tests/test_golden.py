"""``output/golden-tiny/`` - the committed fixture.

Its value is that regenerating it and diffing shows exactly what moved, which
catches the changes nobody thought to write a test for. That only works if two
regenerations agree, so this module pins both halves:

* the fixture on disk is complete and internally consistent;
* a fresh run reproduces it byte for byte, apart from the two wall-clock fields
  an audit log legitimately carries.
"""

from __future__ import annotations

import json

import pytest

from conftest import PREMISE, isolated_root
from novaforge.security.sandbox import Workspace
from novaforge.config import package_root

GOLDEN = package_root() / "output" / "golden-tiny"

# `ts` is when the call happened and `elapsed_s` is how long it took. Both are
# real measurements, so they are not made reproducible; they are excluded from
# the comparison instead.
#
# `hash` and `prev` vary for the same reason, not a second one: the chain hash
# covers the whole row including `ts`. Excluding `ts` from the hash would make
# the timestamp the one field an edit could change undetected, which is the
# opposite of what the chain is for.
WALL_CLOCK_FIELDS = {"ts", "elapsed_s", "hash", "prev"}

# `run_id` identifies one *attempt*. It is deliberately unique per run, so
# that a replaced run gets its own Langfuse trace rather than piling into
# the previous one's. A value that exists to be different cannot also be
# reproducible, so state.json is compared without it.
PER_ATTEMPT_FIELDS = {"run_id"}

pytestmark = pytest.mark.skipif(
    not (GOLDEN / "state.json").exists(),
    reason="golden-tiny has not been generated; see output/golden-tiny/README.md",
)


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def strip_wall_clock(rows):
    return [{k: v for k, v in row.items() if k not in WALL_CLOCK_FIELDS} for row in rows]


class TestTheFixtureIsComplete:
    @pytest.mark.parametrize("name", [
        "README.md", "state.json", "config.snapshot.json", "outline.md", "synopsis.md",
        "bible/world.md", "bible/characters.md", "bible/timeline.md", "bible/mysteries.md",
        "dist/book.md", "dist/book.pdf", "logs/agents.jsonl", "logs/cost.json",
    ])
    def test_the_expected_file_is_present(self, name):
        assert (GOLDEN / name).exists(), name

    def test_it_holds_three_chapters_with_drafts_finals_and_summaries(self):
        for number in (1, 2, 3):
            for suffix in (".md", ".final.md", ".summary.md"):
                assert (GOLDEN / "chapters" / f"ch{number:02d}{suffix}").exists()

    def test_it_holds_the_failing_first_draft_of_chapter_two(self):
        """The README says this is the point of committing it: a reader can see
        the verdict that rejected a draft without running anything."""
        critique = json.loads((GOLDEN / "critiques" / "ch02.continuity.json")
                              .read_text(encoding="utf-8"))
        assert critique["drafts"] == 2
        assert critique["iterations"][0]["findings"][0]["kind"] == "name-drift"
        assert critique["final"]["findings"] == []

    def test_the_readme_is_not_the_placeholder(self):
        text = (GOLDEN / "README.md").read_text(encoding="utf-8")
        assert "NOT YET GENERATED" not in text
        assert "It is empty" not in text


class TestTheFixtureIsConsistent:
    def test_state_agrees_with_the_audit_log(self):
        """The bug that made this test necessary: an append-only log plus a
        second `new` into the same slug described two runs as one."""
        state = json.loads((GOLDEN / "state.json").read_text(encoding="utf-8"))
        rows = read_rows(GOLDEN / "logs" / "agents.jsonl")
        assert sum(1 for r in rows if r["event"] == "call") == state["calls"]

    def test_the_log_describes_exactly_one_run(self):
        rows = read_rows(GOLDEN / "logs" / "agents.jsonl")
        assert sum(1 for r in rows if r["event"] == "stage_complete") == 6
        assert len({r["config_hash"] for r in rows}) == 1

    def test_cost_json_agrees_with_the_log(self):
        rows = read_rows(GOLDEN / "logs" / "agents.jsonl")
        total = sum(r["cost_usd"] for r in rows if r["event"] == "call")
        cost = json.loads((GOLDEN / "logs" / "cost.json").read_text(encoding="utf-8"))
        assert abs(total - cost["cost_usd"]) < 1e-6

    def test_state_agrees_with_the_snapshot(self):
        state = json.loads((GOLDEN / "state.json").read_text(encoding="utf-8"))
        snapshot = json.loads((GOLDEN / "config.snapshot.json").read_text(encoding="utf-8"))
        assert state["config_hash"] == snapshot["config_hash"]
        assert state["stage"] == "complete"
        assert all(c["status"] == "approved" for c in state["chapters"])


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    """A fresh run of **the exact command the README documents**.

    Driven through the CLI rather than the orchestrator directly, because the
    flags are part of what is being reproduced: ``--engine mock`` adds a ``cli``
    layer to ``config.snapshot.json``, so a run wired up any other way produces
    a different snapshot and the byte-for-byte claim would be false.
    """
    from novaforge import cli

    root = isolated_root(tmp_path_factory.mktemp("golden"))
    original = cli.package_root
    cli.package_root = lambda: root
    try:
        exit_code = cli.main(["new", PREMISE, "--slug", "golden-tiny",
                              "--profile", "tiny", "--engine", "mock", "--quiet"])
    finally:
        cli.package_root = original
    assert exit_code == 0
    return Workspace(root / "output" / "golden-tiny", create=False)


class TestItReproduces:
    @pytest.mark.parametrize("name", [
        "bible/world.md", "bible/characters.md", "bible/timeline.md", "bible/mysteries.md",
        "outline.md", "synopsis.md", "dist/book.md",
        "chapters/ch01.md", "chapters/ch02.md", "chapters/ch03.md",
        "chapters/ch01.final.md", "chapters/ch02.final.md", "chapters/ch03.final.md",
        "critiques/ch02.continuity.json", "state.json", "config.snapshot.json",
    ])
    def test_a_fresh_run_reproduces_the_file_byte_for_byte(self, fresh, name):
        mine = fresh.read_text(name)
        theirs = (GOLDEN / name).read_text(encoding="utf-8")
        if name == "state.json":
            # Everything except the per-attempt identity.
            a, b = json.loads(mine), json.loads(theirs)
            for field in PER_ATTEMPT_FIELDS:
                a.pop(field, None)
                b.pop(field, None)
            assert a == b
            return
        assert mine == theirs

    def test_the_audit_log_matches_apart_from_wall_clock_fields(self, fresh):
        mine = read_rows(fresh.root / "logs" / "agents.jsonl")
        theirs = read_rows(GOLDEN / "logs" / "agents.jsonl")
        assert strip_wall_clock(mine) == strip_wall_clock(theirs)

    def test_the_pdf_reproduces_byte_for_byte(self, fresh):
        """A PDF is byte-addressed: if anything moved, the xref offsets moved
        with it, so this is a strict check of the whole layout."""
        assert (fresh.read_bytes("dist/book.pdf")
                == (GOLDEN / "dist" / "book.pdf").read_bytes())

    def test_the_committed_chain_verifies(self):
        """The fixture ships a chain a reader can check for themselves."""
        from novaforge.security.audit import AuditChain
        from novaforge.security.sandbox import Workspace

        assert AuditChain(Workspace(GOLDEN, create=False)).verify().intact

    def test_the_run_id_is_the_only_thing_state_json_cannot_reproduce(self, fresh):
        """Named, so a second unreproducible field is a test failure rather
        than something a reader has to spot in a diff."""
        mine = json.loads(fresh.read_text("state.json"))
        theirs = json.loads((GOLDEN / "state.json").read_text(encoding="utf-8"))
        differing = {k for k in mine if mine[k] != theirs.get(k)}
        assert differing <= PER_ATTEMPT_FIELDS, differing
        assert mine["run_id"] != theirs["run_id"]

    def test_only_the_wall_clock_fields_differ(self, fresh):
        """Named explicitly so that a third varying field is a test failure
        rather than something a reader has to notice in a diff."""
        mine = read_rows(fresh.root / "logs" / "agents.jsonl")
        theirs = read_rows(GOLDEN / "logs" / "agents.jsonl")
        varying = {k for a, b in zip(mine, theirs) for k in a if a[k] != b.get(k)}
        assert varying <= WALL_CLOCK_FIELDS
