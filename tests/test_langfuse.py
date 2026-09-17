"""The Langfuse sink.

Skipped without credentials, like the `live` tests for the Anthropic engine.
That is not a way of avoiding the check: what is skipped is the half that
needs a server. Everything that can be verified offline — that the SDK is not
imported unless asked for, that a missing key fails with instructions rather
than a traceback, that secrets are scrubbed before anything leaves the machine
— runs every time.
"""

from __future__ import annotations

import os

import pytest

from conftest import run_novel
from novaforge.observability import build_sink

HAVE_SDK = True
try:
    import langfuse  # noqa: F401
except ImportError:
    HAVE_SDK = False

HAVE_KEYS = bool(os.environ.get("LANGFUSE_PUBLIC_KEY")
                 and os.environ.get("LANGFUSE_SECRET_KEY"))

needs_sdk = pytest.mark.skipif(not HAVE_SDK, reason="pip install 'novaforge[langfuse]'")
needs_keys = pytest.mark.skipif(
    not HAVE_KEYS,
    reason="set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to run against a project")


class TestItFailsHelpfully:
    @needs_sdk
    def test_missing_credentials_say_what_to_set(self, monkeypatch):
        """And say *where*: the environment, for the same reason SEC-2.1 gives
        for the Anthropic key."""
        from novaforge.observability.langfuse import MissingLangfuse

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        with pytest.raises(MissingLangfuse, match="LANGFUSE_PUBLIC_KEY"):
            build_sink("langfuse")

    @needs_sdk
    def test_the_message_offers_the_way_out(self, monkeypatch):
        from novaforge.observability.langfuse import MissingLangfuse

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        with pytest.raises(MissingLangfuse, match="environment"):
            build_sink("langfuse")


class TestSecretsNeverLeaveTheMachine:
    @needs_sdk
    @needs_keys
    def test_the_keys_themselves_are_scrubbed_from_anything_sent(self):
        """This is the one place in the program where a premise and a model's
        output travel to a third party, so the redactor that protects
        state.json protects this too (SEC-2.2)."""
        sink = build_sink("langfuse")
        secret = os.environ["LANGFUSE_SECRET_KEY"]
        assert secret not in sink._clean(f"the key is {secret}")

    @needs_sdk
    @needs_keys
    def test_an_anthropic_key_in_a_prompt_is_scrubbed(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-SECRETVALUE0001")
        sink = build_sink("langfuse")
        assert "SECRETVALUE" not in sink._clean("key sk-ant-api03-SECRETVALUE0001")

    @needs_sdk
    @needs_keys
    def test_long_fields_are_truncated_after_scrubbing_not_before(self):
        """Truncating first could cut a key in half and leave a fragment the
        patterns no longer recognise."""
        from novaforge.observability.langfuse import MAX_FIELD_CHARS

        sink = build_sink("langfuse")
        secret = os.environ["LANGFUSE_SECRET_KEY"]
        padded = ("x" * MAX_FIELD_CHARS) + f" {secret}"
        out = sink._clean(padded)
        assert secret not in out
        assert len(out) < len(padded)


class TestAgainstARealProject:
    @needs_sdk
    @needs_keys
    def test_the_credentials_reach_the_project(self):
        assert build_sink("langfuse").check()

    @needs_sdk
    @needs_keys
    def test_a_whole_run_arrives_as_one_trace(self, tmp_path):
        sink = build_sink("langfuse")
        _, state, _ = run_novel(tmp_path, slug="lf", sink=sink)
        assert state.stage == "complete"
        assert sink.url(), "the run produced no trace url"

    @needs_sdk
    @needs_keys
    def test_a_resumed_run_extends_its_trace_rather_than_starting_a_second(self, tmp_path):
        """The trace id is seeded from slug and config hash, so the same novel
        keeps the same trace across a resume."""
        from langfuse import Langfuse

        a = Langfuse.create_trace_id(seed="slug|abc123")
        b = Langfuse.create_trace_id(seed="slug|abc123")
        c = Langfuse.create_trace_id(seed="slug|def456")
        assert a == b and a != c
