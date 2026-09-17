"""Observability, which is additive and must stay that way.

Two properties are defended here, and they matter more than anything the sink
actually sends:

* **A sink never changes a run.** Not its artefacts, not its audit chain, not
  whether it succeeds. An observability backend that could fail a novel would
  be a worse deal than no observability at all.
* **Unconfigured means unchanged.** The default is a sink that does nothing,
  nothing imports the Langfuse SDK unless it is asked for, and a run without it
  is the offline zero-dependency run the project promises.

The Langfuse sink itself is covered in `tests/test_langfuse.py`, which skips
without credentials.
"""

from __future__ import annotations

import pytest

from conftest import run_novel
from novaforge.config import load_config
from novaforge.observability import NullSink, RunSink, build_sink
from novaforge.observability.base import safely


class TestTheDefault:
    def test_the_shipped_config_sends_runs_to_langfuse(self):
        """CFG-11 — the project has moved to Langfuse, so that is the
        default. Turning it off is a config change, not the other way
        round."""
        assert load_config().get("observability.sink") == "langfuse"
        assert load_config(profile="tiny").get("observability.sink") == "langfuse"

    def test_it_can_still_be_turned_off_for_an_offline_run(self):
        config = load_config(profile="tiny",
                             overrides={"observability": {"sink": "none"}})
        assert isinstance(build_sink(config.get("observability.sink")), NullSink)

    def test_langfuse_without_credentials_degrades_to_silence(self, monkeypatch):
        """CFG-11 — configured but unusable is the same as unreachable, and
        a dashboard that cannot be reached must not stop a novel."""
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        said: list[str] = []
        assert isinstance(build_sink("langfuse", report=said.append), NullSink)
        assert said and "not sending" in said[0]

    @pytest.mark.parametrize("name", [None, "", "none", "off", "NONE"])
    def test_every_way_of_saying_off(self, name):
        assert isinstance(build_sink(name), NullSink)

    def test_an_unknown_sink_raises_rather_than_falling_back(self):
        """Falling back to silence would mean a typo in --trace quietly sends a
        run nowhere while the operator believes it is being traced."""
        with pytest.raises(ValueError, match="unknown observability sink"):
            build_sink("langfsue")

    def test_the_sdk_is_not_imported_at_module_load(self):
        """Importing the package must not import Langfuse. The SDK is
        reached only when a run is built, so `import novaforge` stays as
        cheap and as dependency-free as it ever was."""
        import subprocess
        import sys

        code = ("import sys, novaforge.orchestrator, novaforge.cli;"
                "print('langfuse' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, check=True).stdout.strip()
        assert out == "False"


class TestASinkNeverChangesARun:
    def test_a_run_with_the_null_sink_is_the_run_it_always_was(self, tmp_path):
        _, state, space = run_novel(tmp_path, slug="null")
        assert state.stage == "complete"
        assert space.exists("dist/book.md") and space.exists("logs/agents.jsonl")

    def test_a_sink_that_throws_on_every_call_costs_the_run_nothing(self, tmp_path):
        """CFG-11 — a sink may never change a run. A hosted service is
        exactly the kind of thing that is down on the afternoon you need to
        finish a book."""
        orch, state, space = run_novel(tmp_path, slug="angry", sink=_Exploding())
        assert state.stage == "complete"
        assert len(state.chapters) == 3
        assert orch.verify_chain().intact

    def test_a_failing_sink_is_reported_rather_than_swallowed(self):
        """An operator who thinks a run is traced and finds nothing later is
        worse off than one who saw a line saying it was not."""
        seen: list[str] = []
        safely(lambda: (_ for _ in ()).throw(RuntimeError("boom")),
               on_error=seen.append)
        assert seen and "boom" in seen[0]

    def test_safely_lets_a_working_action_through(self):
        done: list[int] = []
        safely(lambda: done.append(1))
        assert done == [1]

    def test_the_audit_chain_is_unaffected_by_the_sink(self, tmp_path):
        """CFG-11 — additive, never authoritative. logs/agents.jsonl stays
        the record; a sink is a copy for looking at."""
        a, _, space_a = run_novel(tmp_path / "a", slug="x")
        b, _, space_b = run_novel(tmp_path / "b", slug="x", sink=_Exploding())
        assert a.verify_chain().intact and b.verify_chain().intact
        assert space_a.read_text("dist/book.md") == space_b.read_text("dist/book.md")


class TestTheSinkCanBeHeard:
    """A sink that cannot report is a sink whose failures are invisible.

    The orchestrator built one with no reporter, so `LangfuseSink`'s own
    `safely` calls went nowhere: its trace URL never printed, and a failed call
    to Langfuse looked exactly like a successful one. Found by running against
    a real project and noticing the URL line was missing — the failure mode was
    silence, which is the only failure mode nobody notices.
    """

    def test_the_orchestrator_hands_the_reporter_to_the_sink_itself(self, tmp_path):
        said: list[str] = []
        run_novel(tmp_path, slug="heard", report=said.append,
                  overrides={"observability": {"sink": "talkative"}})
        assert any("talkative sink speaking" in line for line in said), said

    def test_a_sink_built_without_options_still_works(self):
        """The default path must not depend on being handed anything."""
        assert isinstance(build_sink("none"), NullSink)

    def test_the_configured_environment_reaches_the_sink(self, tmp_path):
        said: list[str] = []
        run_novel(tmp_path, slug="envt", report=said.append,
                  overrides={"observability": {"sink": "talkative",
                                               "environment": "staging"}})
        assert any("environment=staging" in line for line in said), said


class TestTheInterface:
    def test_the_null_sink_satisfies_it(self):
        assert isinstance(NullSink(), RunSink)

    def test_it_reports_no_url_when_there_is_nowhere_to_look(self):
        assert NullSink().url() is None

    def test_a_sink_receives_one_call_per_model_call(self, tmp_path):
        sink = _Counting()
        _, state, _ = run_novel(tmp_path, slug="count", sink=sink)
        assert sink.calls == state.calls
        assert sink.gates >= len(state.chapters)
        assert sink.started == 1 and sink.finished == 1

    def test_the_gate_events_come_from_the_audit_log_not_from_stages(self, tmp_path):
        """A stage never talks to a sink. It emits an audit row, and the sink
        reads the rows the log was already writing."""
        import inspect

        from novaforge.stages import chapters, publish, style

        for module in (chapters, publish, style):
            assert "sink" not in inspect.getsource(module)


# -- doubles -----------------------------------------------------------------


class _Exploding:
    name = "exploding"

    def _boom(self, **_):
        raise RuntimeError("the dashboard is on fire")

    start_run = record_call = record_gate = finish_run = _boom

    def url(self):
        raise RuntimeError("also on fire")


class _Counting:
    name = "counting"

    def __init__(self):
        self.started = self.finished = self.calls = self.gates = 0

    def start_run(self, **_):
        self.started += 1

    def record_call(self, **_):
        self.calls += 1

    def record_gate(self, **_):
        self.gates += 1

    def finish_run(self, **_):
        self.finished += 1

    def url(self):
        return None
