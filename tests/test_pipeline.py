"""The whole pipeline, end to end, against the real orchestrator.

These are the tests that would have caught every bug found so far, because
they exercise the seams rather than the units: the spec driving the stage
order, the gate rejecting and re-drafting, the context policy holding across
chapters, and the artefacts landing where the RUNBOOK says to look for them.
"""

from __future__ import annotations

import json

import pytest

from conftest import PREMISE, run_novel


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    """One full tiny run, shared by every test that only reads it."""
    lines: list[str] = []
    orch, state, space = run_novel(tmp_path_factory.mktemp("run"),
                                   report=lines.append)
    return orch, state, space, lines


class TestItRuns:
    def test_the_run_completes(self, completed):
        _, state, _, _ = completed
        assert state.stage == "complete"

    def test_every_stage_in_the_spec_ran_in_order(self, completed, flow):
        _, state, _, _ = completed
        assert state.completed_stages == [s.id for s in flow]

    def test_three_chapters_were_written(self, completed, config):
        _, state, _, _ = completed
        assert len(state.chapters) == config.get("novel.chapters")

    def test_every_chapter_cleared_the_gate(self, completed):
        _, state, _, _ = completed
        assert all(c["status"] == "approved" for c in state.chapters)

    def test_the_run_cost_something_and_counted_it(self, completed):
        _, state, _, _ = completed
        assert state.calls > 0
        assert state.cost_usd > 0
        assert state.input_tokens > 0 and state.output_tokens > 0


class TestArtefacts:
    """The RUNBOOK §4 table, as assertions."""

    @pytest.mark.parametrize("path", [
        "bible/world.md", "bible/characters.md", "bible/timeline.md",
        "bible/mysteries.md", "outline.md", "synopsis.md",
        "config.snapshot.json", "state.json",
        "logs/agents.jsonl", "logs/cost.json", "dist/book.md",
    ])
    def test_the_expected_artefact_exists(self, completed, path):
        _, _, space, _ = completed
        assert space.exists(path), path

    def test_one_draft_and_one_summary_per_chapter(self, completed, config):
        _, _, space, _ = completed
        chapters = config.get("novel.chapters")
        assert len(space.glob("chapters/ch*.md")) == chapters * 3  # draft, final, summary

    def test_one_critique_file_per_critic_per_chapter(self, completed, config):
        _, _, space, _ = completed
        expected = config.get("novel.chapters") * len(config.get("quality_gate.critics"))
        assert len(space.glob("critiques/*.json")) == expected

    def test_the_config_snapshot_is_the_resolved_config(self, completed, config):
        _, _, space, _ = completed
        snapshot = space.read_json("config.snapshot.json")
        assert snapshot["config_hash"] == config.hash
        assert snapshot["resolved"]["novel"]["chapters"] == 3
        assert "config/profiles/tiny.json" in snapshot["layers"]

    def test_state_records_the_config_hash(self, completed, config):
        _, _, space, _ = completed
        assert space.read_json("state.json")["config_hash"] == config.hash


class TestTheGate:
    def test_chapter_two_is_rejected_then_repaired(self, completed):
        """The point of the whole loop. A run where everything passes first
        time would prove nothing about the gate."""
        _, state, _, lines = completed
        report = "\n".join(lines)
        assert "ch02 draft 1" in report and "-> retry" in report
        assert "ch02 draft 2" in report
        ch02 = next(c for c in state.chapters if c["number"] == 2)
        assert ch02["iterations"] == 2
        assert ch02["status"] == "approved"

    def test_the_rejection_was_the_drifted_surname(self, completed):
        _, _, space, _ = completed
        critique = space.read_json("critiques/ch02.continuity.json")
        first = critique["iterations"][0]
        assert first["findings"][0]["kind"] == "name-drift"
        assert first["findings"][0]["quote"] == "Kassar"

    def test_the_rejected_draft_is_kept_as_evidence(self, completed):
        """RUNBOOK §4: iterations[0] has the finding, final.findings is empty."""
        _, _, space, _ = completed
        critique = space.read_json("critiques/ch02.continuity.json")
        assert critique["drafts"] == 2
        assert critique["iterations"][0]["findings"]
        assert critique["final"]["findings"] == []

    def test_chapters_that_passed_took_one_draft(self, completed):
        _, state, _, _ = completed
        for number in (1, 3):
            assert next(c for c in state.chapters if c["number"] == number)["iterations"] == 1

    def test_every_chapter_is_in_the_configured_length_band(self, completed, config):
        _, state, _, _ = completed
        low = config.get("novel.words_per_chapter.min")
        high = config.get("novel.words_per_chapter.max")
        for chapter in state.chapters:
            assert low <= chapter["words"] <= high, chapter


class TestGateIsConfigurable:
    def test_an_impossible_threshold_falls_through_to_accept_with_warnings(self, tmp_path):
        """CFG: the threshold is a number in JSON, and changing it changes what
        this loop accepts - with no Python edited."""
        _, state, _ = run_novel(tmp_path, slug="strict", overrides={
            "novel": {"words_per_chapter": {"target": 100}}})
        assert all(c["status"] == "accepted_with_warnings" for c in state.chapters)
        assert all(c["warnings"] for c in state.chapters)

    def test_it_keeps_the_best_draft_not_the_last(self, tmp_path):
        _, state, space = run_novel(tmp_path, slug="best", overrides={
            "novel": {"words_per_chapter": {"target": 100}}})
        for chapter in state.chapters:
            recorded = min(chapter["scores"].values())
            critiques = [space.read_json(f"critiques/ch{chapter['number']:02d}.{c}.json")
                         for c in ("continuity", "length", "science")]
            best_possible = max(
                min(c["iterations"][i]["score"] for c in critiques)
                for i in range(len(critiques[0]["iterations"]))
            )
            assert recorded == best_possible

    def test_fewer_revisions_means_fewer_drafts(self, tmp_path):
        _, state, _ = run_novel(tmp_path, slug="one", overrides={
            "quality_gate": {"max_revisions": 0}})
        assert all(c["iterations"] == 1 for c in state.chapters)
        # ch02 drifts on its only draft, so it cannot be approved.
        assert next(c for c in state.chapters
                    if c["number"] == 2)["status"] == "accepted_with_warnings"

    def test_disabling_drift_makes_every_chapter_pass_first_time(self, tmp_path):
        _, state, _ = run_novel(tmp_path, slug="nodrift",
                                overrides={"engine": {"inject_drift": False}})
        assert all(c["iterations"] == 1 for c in state.chapters)
        assert all(c["status"] == "approved" for c in state.chapters)


class TestContextPolicy:
    def test_no_prior_prose_ever_reached_the_writer(self, completed):
        """FLOW-4's guarantee is enforced at runtime inside the stage: if any
        earlier chapter's wording had leaked, the run would have raised."""
        _, state, _, _ = completed
        assert state.stage == "complete"

    def test_a_violation_would_actually_halt_the_run(self, completed):
        """The guard is only worth having if it can fail. Proven directly."""
        from novaforge.context import ContextPolicyViolation, assert_no_prior_prose
        _, _, space, _ = completed
        chapter_one = space.read_text("chapters/ch01.md")
        stolen = " ".join(chapter_one.split()[5:25])
        with pytest.raises(ContextPolicyViolation):
            assert_no_prior_prose(stolen, [chapter_one])


class TestAudit:
    def test_one_row_per_call_plus_stage_and_bible_events(self, completed):
        _, state, space, _ = completed
        rows = [json.loads(line) for line in space.read_lines("logs/agents.jsonl")]
        assert sum(1 for r in rows if r["event"] == "call") == state.calls
        assert sum(1 for r in rows if r["event"] == "stage_complete") == 6
        assert sum(1 for r in rows if r["event"] == "bible_write") == 4

    def test_the_gate_records_why_each_chapter_was_accepted(self, completed):
        """Without these rows the log says which calls happened but not why a
        chapter was accepted, which stops one question short of reconstructing
        the run."""
        _, _, space, _ = completed
        rows = [json.loads(line) for line in space.read_lines("logs/agents.jsonl")]
        gate = [r for r in rows if r["event"] == "gate_decision"]
        assert len(gate) == 4  # ch01, ch02 twice, ch03
        assert [r["verdict"] for r in gate] == ["accept", "retry", "accept", "accept"]
        for row in gate:
            assert row["flow_id"] == "FLOW-4"
            assert set(row["scores"]) == {"continuity", "science", "length"}
            assert row["aggregate_score"] == min(row["scores"].values())
            assert (row["aggregate_score"] >= row["threshold"]) == (row["verdict"] != "retry")

    def test_every_row_carries_the_config_hash(self, completed, config):
        _, _, space, _ = completed
        rows = [json.loads(line) for line in space.read_lines("logs/agents.jsonl")]
        assert all(r["config_hash"] == config.hash for r in rows)

    def test_every_call_names_its_flow_id(self, completed):
        _, _, space, _ = completed
        calls = [json.loads(line) for line in space.read_lines("logs/agents.jsonl")
                 if json.loads(line)["event"] == "call"]
        assert {c["flow_id"] for c in calls} == {f"FLOW-{i}" for i in range(1, 7)}

    def test_the_spec_substitution_is_recorded(self, completed):
        """The spec on disk is not quite what ran, and the log says so."""
        _, _, space, _ = completed
        rows = [json.loads(line) for line in space.read_lines("logs/agents.jsonl")]
        assert any(r["event"] == "spec_substitution" for r in rows)

    def test_the_logged_cost_matches_cost_json(self, completed):
        _, _, space, _ = completed
        calls = [json.loads(line) for line in space.read_lines("logs/agents.jsonl")
                 if json.loads(line)["event"] == "call"]
        total = sum(c["cost_usd"] for c in calls)
        assert abs(total - space.read_json("logs/cost.json")["cost_usd"]) < 1e-6


class TestManuscript:
    def test_the_book_contains_every_chapter(self, completed, config):
        _, _, space, _ = completed
        book = space.read_text("dist/book.md")
        for number in range(1, config.get("novel.chapters") + 1):
            assert f"Chapter {number}" in book

    def test_it_is_wrapped_at_the_configured_width(self, completed, config):
        _, _, space, _ = completed
        width = config.get("novel.chars_per_line.max")
        assert max(len(l) for l in space.read_text("dist/book.md").splitlines()) <= width

    def test_it_carries_a_table_of_contents_and_the_synopsis(self, completed):
        _, _, space, _ = completed
        book = space.read_text("dist/book.md")
        assert "## Contents" in book and "## Synopsis" in book

    def test_every_configured_format_is_written(self, completed, config):
        _, state, space, _ = completed
        assert config.get("outputs.formats") == ["markdown", "pdf"]
        assert space.exists("dist/book.md") and space.exists("dist/book.pdf")
        assert not state.notes  # nothing was quietly skipped

    def test_a_format_it_cannot_write_is_reported_by_name(self, tmp_path):
        """A run that quietly writes one file when the config asked for two is
        a run that lies in its summary."""
        lines: list[str] = []
        _, state, space = run_novel(tmp_path, slug="fmt", report=lines.append, overrides={
            "outputs": {"formats": ["markdown", "papyrus"]}})
        assert any("papyrus" in note for note in state.notes)
        assert any("NOT WRITTEN" in line for line in lines)
        assert space.exists("dist/book.md")

    def test_each_exporter_describes_itself(self, completed):
        """'wrapped at 64 columns' is true of the Markdown and false of the
        PDF, which is paginated at a measured width."""
        _, _, _, lines = completed
        report = "\n".join(lines)
        assert "book.md — 3 chapters" in report and "wrapped at 64 columns" in report
        assert "book.pdf — " in report and "pages, A5" in report


class TestSpecDrivesOrder:
    def test_the_orchestrator_holds_no_stage_list(self):
        """Reorder specs/flow.yaml and the run changes with no Python edited."""
        import inspect
        from novaforge import orchestrator
        source = inspect.getsource(orchestrator)
        assert "FLOW-1" not in source
        assert "worldbuilder" not in source

    def test_the_chapter_loop_holds_no_threshold_literal(self):
        import inspect
        from novaforge.stages import chapters
        source = inspect.getsource(chapters.ChapterLoopStage)
        assert "threshold=8" not in source and "score >= 8" not in source
