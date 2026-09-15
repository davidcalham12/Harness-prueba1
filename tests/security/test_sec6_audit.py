"""SEC-6 - the audit chain and the spend ceilings.

The chain tests are written around what the chain actually promises. It is
tamper-**evident**, not tamper-**proof**, so there is a test that a wholesale
rewrite *succeeds* without the key - stating the limit rather than leaving a
reader to assume a guarantee that is not there - and a test that the same
forgery fails once ``NOVAFORGE_AUDIT_KEY`` is set.

The budget tests care about one thing above correctness: the ceiling is checked
*before* the call. A guard that reports the overrun afterwards has already
spent the money.
"""

from __future__ import annotations

import json

import pytest

from novaforge.security.audit import (
    GENESIS,
    AuditChain,
    Budget,
    BudgetExceeded,
    BudgetGuard,
)


def rows_of(workspace, path="logs/agents.jsonl"):
    return [json.loads(line) for line in workspace.read_lines(path)]


def rewrite(workspace, rows, path="logs/agents.jsonl"):
    (workspace.root / "logs").mkdir(parents=True, exist_ok=True)
    (workspace.root / "logs" / "agents.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")


@pytest.fixture
def chain(workspace):
    link = AuditChain(workspace)
    for index in range(6):
        link.append({"event": "call", "n": index, "cost_usd": 0.01})
    return link


class TestChainShape:
    def test_every_row_carries_seq_prev_and_hash(self, chain, workspace):
        for index, row in enumerate(rows_of(workspace)):
            assert row["seq"] == index
            assert len(row["hash"]) == 64
            assert "prev" in row

    def test_the_first_row_links_to_genesis(self, chain, workspace):
        assert rows_of(workspace)[0]["prev"] == GENESIS

    def test_each_row_links_to_the_one_before_it(self, chain, workspace):
        rows = rows_of(workspace)
        for previous, current in zip(rows, rows[1:]):
            assert current["prev"] == previous["hash"]

    def test_an_intact_chain_verifies(self, chain):
        report = chain.verify()
        assert report.intact
        assert report.rows == 6
        assert "chain intact" in str(report)

    def test_a_resumed_run_extends_the_chain(self, chain, workspace):
        """Rather than starting a second one beside it."""
        second = AuditChain(workspace)
        second.append({"event": "call", "n": 99})
        rows = rows_of(workspace)
        assert rows[-1]["seq"] == 6
        assert rows[-1]["prev"] == rows[-2]["hash"]
        assert second.verify().intact


class TestTamperDetection:
    def test_an_edited_row_is_caught(self, chain, workspace):
        rows = rows_of(workspace)
        rows[3]["cost_usd"] = 0.0
        rewrite(workspace, rows)
        report = AuditChain(workspace).verify()
        assert not report.intact
        assert any("row 3 was edited" in p for p in report.problems)

    def test_a_removed_row_is_caught(self, chain, workspace):
        rows = rows_of(workspace)
        del rows[2]
        rewrite(workspace, rows)
        report = AuditChain(workspace).verify()
        assert not report.intact
        assert any("removed" in p for p in report.problems)

    def test_an_inserted_row_is_caught(self, chain, workspace):
        rows = rows_of(workspace)
        rows.insert(2, dict(rows[2]))
        rewrite(workspace, rows)
        assert not AuditChain(workspace).verify().intact

    def test_reordered_rows_are_caught(self, chain, workspace):
        rows = rows_of(workspace)
        rows[1], rows[4] = rows[4], rows[1]
        rewrite(workspace, rows)
        assert not AuditChain(workspace).verify().intact

    def test_unparseable_rows_are_reported_not_crashed_on(self, chain, workspace):
        (workspace.root / "logs" / "agents.jsonl").write_text(
            "not json at all\n", encoding="utf-8")
        report = AuditChain(workspace).verify()
        assert not report.intact
        assert any("not valid JSON" in p for p in report.problems)

    def test_every_problem_is_reported_not_just_the_first(self, chain, workspace):
        rows = rows_of(workspace)
        rows[1]["n"] = 999
        rows[4]["n"] = 999
        rewrite(workspace, rows)
        problems = AuditChain(workspace).verify().problems
        assert any("row 1" in p for p in problems)
        assert any("row 4" in p for p in problems)


class TestTheStatedLimit:
    def test_without_a_key_a_wholesale_rewrite_verifies(self, chain, workspace):
        """Tamper-EVIDENT, not tamper-PROOF. Stated as a test so no reader
        assumes a guarantee the design does not make."""
        rows = [{k: v for k, v in r.items() if k not in ("seq", "prev", "hash")}
                for r in rows_of(workspace)]
        rows[3]["cost_usd"] = 0.0
        (workspace.root / "logs" / "agents.jsonl").unlink()
        forged = AuditChain(workspace)
        for row in rows:
            forged.append(row)
        assert AuditChain(workspace).verify().intact is True

    def test_with_a_key_the_same_forgery_fails(self, workspace):
        keyed = AuditChain(workspace, key="s3cret")
        for index in range(4):
            keyed.append({"event": "call", "n": index})
        assert AuditChain(workspace, key="s3cret").verify().intact
        assert not AuditChain(workspace, key=None).verify().intact
        assert not AuditChain(workspace, key="a-different-key").verify().intact

    def test_the_report_says_which_kind_of_chain_it_checked(self, workspace):
        keyed = AuditChain(workspace, key="s3cret")
        keyed.append({"event": "call"})
        assert "HMAC chain" in str(keyed.verify())

    def test_the_key_is_read_from_the_environment(self, workspace, monkeypatch):
        monkeypatch.setenv("NOVAFORGE_AUDIT_KEY", "from-the-env")
        assert AuditChain(workspace).keyed


class TestBudgetGuard:
    BUDGET = Budget(max_cost_usd=1.0, max_calls=10, max_tokens=1000)

    def test_a_fresh_guard_permits_a_call(self):
        BudgetGuard(self.BUDGET).check()

    def test_the_call_ceiling_stops_the_run(self):
        guard = BudgetGuard(self.BUDGET, calls=10)
        with pytest.raises(BudgetExceeded, match="call ceiling"):
            guard.check()

    def test_the_cost_ceiling_stops_the_run(self):
        with pytest.raises(BudgetExceeded, match="cost ceiling"):
            BudgetGuard(self.BUDGET, spent_usd=1.0).check()

    def test_the_token_ceiling_stops_the_run(self):
        with pytest.raises(BudgetExceeded, match="token ceiling"):
            BudgetGuard(self.BUDGET, tokens=1000).check()

    def test_the_message_names_the_config_key_to_raise(self):
        with pytest.raises(BudgetExceeded, match="budget.max_calls"):
            BudgetGuard(self.BUDGET, calls=10).check()

    def test_it_is_checked_before_the_call_not_after(self):
        """The ceiling is a ceiling, not a report of how far past it the run
        went. Ten calls are permitted; the eleventh is refused before it
        happens."""
        guard = BudgetGuard(self.BUDGET)
        for _ in range(10):
            guard.check()
            guard.record(cost_usd=0.0, input_tokens=0, output_tokens=0)
        with pytest.raises(BudgetExceeded):
            guard.check()
        assert guard.calls == 10  # not 11

    def test_recording_accumulates(self):
        guard = BudgetGuard(self.BUDGET)
        guard.record(cost_usd=0.25, input_tokens=100, output_tokens=50)
        assert guard.calls == 1 and guard.spent_usd == 0.25 and guard.tokens == 150

    def test_remaining_never_goes_negative(self):
        guard = BudgetGuard(self.BUDGET, spent_usd=5.0, calls=99, tokens=99999)
        assert all(value >= 0 for value in guard.remaining.values())

    def test_a_resumed_guard_restores_the_counters(self):
        """So a limit spans the whole novel rather than resetting every time it
        is continued."""
        class _State:
            cost_usd, calls, input_tokens, output_tokens = 0.5, 7, 300, 200

        guard = BudgetGuard.resumed(self.BUDGET, _State())
        assert guard.calls == 7 and guard.spent_usd == 0.5 and guard.tokens == 500

    def test_it_reads_its_ceilings_from_the_config(self, config):
        budget = Budget.from_config(config)
        assert budget.max_cost_usd == config.get("budget.max_cost_usd")
        assert budget.max_calls == config.get("budget.max_calls")
        assert budget.max_tokens == config.get("budget.max_tokens")


class TestBudgetInARun:
    def test_a_ceiling_stops_the_run_cleanly_and_it_stays_resumable(self, tmp_path):
        from conftest import run_novel

        with pytest.raises(BudgetExceeded):
            run_novel(tmp_path, slug="cap", overrides={"budget": {"max_calls": 5}})
        state = json.loads((tmp_path / "cap" / "state.json").read_text("utf-8"))
        assert state["calls"] == 5
        assert state["stage"] != "complete"
        assert state["completed_stages"]  # progress was kept

    def test_the_stop_is_recorded_in_the_audit_log(self, tmp_path):
        from conftest import run_novel

        with pytest.raises(BudgetExceeded):
            run_novel(tmp_path, slug="cap2", overrides={"budget": {"max_calls": 4}})
        rows = [json.loads(l) for l in
                (tmp_path / "cap2" / "logs" / "agents.jsonl").read_text("utf-8").splitlines()
                if l.strip()]
        assert any(r["event"] == "budget_exceeded" for r in rows)

    def test_the_chain_is_still_intact_after_a_budget_stop(self, tmp_path):
        from conftest import run_novel
        from novaforge.security.sandbox import Workspace

        with pytest.raises(BudgetExceeded):
            run_novel(tmp_path, slug="cap3", overrides={"budget": {"max_calls": 4}})
        assert AuditChain(Workspace(tmp_path / "cap3", create=False)).verify().intact

    def test_force_starts_a_fresh_chain_that_verifies(self, tmp_path, monkeypatch):
        """`new --force` deletes the log after the orchestrator has been built.
        A chain still counting from the old file writes seq 31 into a brand-new
        log whose first row should be 0, linked to a hash that no longer exists
        anywhere - and the result reads as tampered, which is the wrong answer
        for a directory that was deliberately replaced."""
        from conftest import isolated_root
        from novaforge import cli
        from novaforge.security.sandbox import Workspace

        root = isolated_root(tmp_path)
        monkeypatch.setattr(cli, "package_root", lambda: root)
        premise = "A salvage crew finds a derelict that remembers them"
        for extra in ([], ["--force"]):
            assert cli.main(["new", premise, "--slug", "twice", "--profile", "tiny",
                             "--engine", "mock", "--quiet"] + extra) == 0

        space = Workspace(root / "output" / "twice", create=False)
        rows = rows_of(space)
        assert rows[0]["seq"] == 0
        assert rows[0]["prev"] == GENESIS
        assert AuditChain(space).verify().intact

    def test_a_generous_ceiling_does_not_interfere(self, tmp_path):
        from conftest import run_novel

        _, state, _ = run_novel(tmp_path, slug="loose")
        assert state.stage == "complete"
