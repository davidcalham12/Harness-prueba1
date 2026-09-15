"""SEC-2 - the credential, and keeping it out of what the run writes.

Two claims, tested separately because they fail differently:

* the key is read from the environment and **only** from there — a ``--api-key``
  flag would land in shell history and the process table;
* everything the run writes or prints is scrubbed.

The scope is also tested, because a redactor that is assumed to cover more than
it does is worse than one that covers less: the manuscript is *not* redacted,
on purpose, and SEC-1.4 is what catches a credential before it can get there.
"""

from __future__ import annotations

import json

import pytest

from novaforge.security.secrets import (
    KEY_ENV,
    PLACEHOLDER,
    MissingCredential,
    Redactor,
    load_api_key,
)

KEY = "sk-ant-api03-REALSECRETVALUE0123456789"


class TestLoadingTheKey:
    def test_it_comes_from_the_environment(self):
        assert load_api_key({KEY_ENV: KEY}) == KEY

    def test_whitespace_is_trimmed(self):
        assert load_api_key({KEY_ENV: f"  {KEY}  "}) == KEY

    def test_a_missing_key_raises_with_instructions(self):
        with pytest.raises(MissingCredential, match="export"):
            load_api_key({})

    def test_an_empty_key_is_the_same_as_missing(self):
        with pytest.raises(MissingCredential):
            load_api_key({KEY_ENV: "   "})

    def test_the_message_explains_why_there_is_no_flag(self):
        with pytest.raises(MissingCredential, match="process table"):
            load_api_key({})

    def test_there_is_no_api_key_flag_anywhere_in_the_cli(self):
        """SEC-2.1, checked against the source rather than promised in a doc."""
        import inspect
        from novaforge import cli

        assert "--api-key" not in inspect.getsource(cli)
        assert "api_key" not in inspect.getsource(cli)


class TestRedactingPatterns:
    redactor = Redactor()

    @pytest.mark.parametrize("secret", [
        "sk-ant-api03-AAAAAAAAAAAAAAAAAAAA",
        "sk-proj-AAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "eyJhbGciOiJIUzI1NiI.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4",
    ])
    def test_key_shaped_strings_are_scrubbed(self, secret):
        out = self.redactor.scrub(f"the value is {secret} ok")
        assert secret not in out
        assert PLACEHOLDER in out

    @pytest.mark.parametrize("line", [
        "api_key=hunter2hunter2hunter2",
        "API_KEY: hunter2hunter2hunter2",
        "password = hunter2hunter2hunter2",
        'token: "hunter2hunter2hunter2"',
        '"secret": "hunter2hunter2hunter2"',
    ])
    def test_assignments_are_scrubbed_whatever_the_value_looks_like(self, line):
        out = self.redactor.scrub(line)
        assert "hunter2" not in out
        assert PLACEHOLDER in out

    def test_the_key_name_survives_so_the_log_still_says_what_was_set(self):
        """Replacing the whole line would lose the fact that a key was
        configured at all, which is a thing an operator needs to know."""
        assert "api_key" in self.redactor.scrub("api_key=hunter2hunter2hunter2")

    @pytest.mark.parametrize("line", [
        "Bearer abcdefghijklmnopqrstuvwxyz",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        "basic YWxhZGRpbjpvcGVuc2VzYW1l",
    ])
    def test_bearer_and_basic_tokens_are_scrubbed(self, line):
        assert "abcdefghijklmnopqrstuvwxyz" not in self.redactor.scrub(line)
        assert "YWxhZGRpbjpvcGVuc2VzYW1l" not in self.redactor.scrub(line)

    @pytest.mark.parametrize("text", [
        "Mara Kassab checked the hatch and said nothing about it.",
        "The chapter scored 10/10 on continuity.",
        "wrote dist/book.pdf — 7 pages, A5, 10pt Helvetica",
        "", "   ",
    ])
    def test_ordinary_text_is_untouched(self, text):
        """A redactor that mangles prose gets turned off, and then it protects
        nothing."""
        assert self.redactor.scrub(text) == text


class TestRedactingLiterals:
    def test_the_live_key_is_scrubbed_as_an_exact_string(self):
        """The case patterns would miss: a provider whose keys look like
        nothing this module has heard of."""
        odd = "zzzz-not-a-recognised-shape-9999"
        assert Redactor(literals=(odd,)).scrub(f"value {odd} here") == \
            f"value {PLACEHOLDER} here"

    def test_it_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv(KEY_ENV, KEY)
        assert KEY not in Redactor.from_env().scrub(f"leaked: {KEY}")

    def test_it_also_covers_the_audit_key(self, monkeypatch):
        monkeypatch.setenv("NOVAFORGE_AUDIT_KEY", "audit-secret-value-1234")
        assert "audit-secret-value-1234" not in \
            Redactor.from_env().scrub("key is audit-secret-value-1234")

    def test_it_works_with_no_key_set(self, monkeypatch):
        """The mock engine needs no credential, and the redactor is on the
        logging path either way."""
        monkeypatch.delenv(KEY_ENV, raising=False)
        monkeypatch.delenv("NOVAFORGE_AUDIT_KEY", raising=False)
        assert Redactor.from_env().scrub("ordinary text") == "ordinary text"

    def test_very_short_values_are_not_treated_as_literals(self, monkeypatch):
        """Redacting a two-character string would gut ordinary prose."""
        monkeypatch.setenv(KEY_ENV, "ab")
        assert Redactor.from_env().scrub("a cab arrived") == "a cab arrived"


class TestRedactingStructures:
    def test_nested_dicts_and_lists_are_scrubbed(self):
        """state.json and every audit row are nested, so scrubbing only the
        top-level string would scrub almost nothing."""
        data = {"a": [{"b": f"api_key={'x' * 20}"}], "n": 1, "ok": None}
        out = Redactor().scrub_data(data)
        assert PLACEHOLDER in out["a"][0]["b"]
        assert out["n"] == 1 and out["ok"] is None

    def test_non_strings_pass_through_unchanged(self):
        assert Redactor().scrub_data({"n": 3, "f": 1.5, "b": True}) == \
            {"n": 3, "f": 1.5, "b": True}


class TestInARun:
    PREMISE = ("A salvage crew finds a derelict, and the flight recorder "
               "still answers questions it was asked before")

    def test_the_key_never_reaches_state_or_the_log(self, tmp_path, monkeypatch):
        from conftest import run_novel

        monkeypatch.setenv(KEY_ENV, KEY)
        _, _, space = run_novel(tmp_path, slug="redact")
        for name in ("state.json", "logs/agents.jsonl", "logs/cost.json"):
            assert KEY not in space.read_text(name), name

    def test_every_line_the_cli_prints_is_scrubbed(self, tmp_path, monkeypatch, capsys):
        """SEC-2.2 says *every* line, and the banner quotes the premise. An
        earlier version redacted only what the orchestrator emitted, and the
        header printed the secret straight through."""
        from conftest import isolated_root
        from novaforge import cli

        root = isolated_root(tmp_path)
        monkeypatch.setattr(cli, "package_root", lambda: root)
        monkeypatch.setenv(KEY_ENV, KEY)
        cli.main(["new", self.PREMISE, "--slug", "banner", "--profile", "tiny",
                  "--engine", "mock"])
        captured = capsys.readouterr()
        assert KEY not in captured.out
        assert KEY not in captured.err

    def test_the_manuscript_is_deliberately_not_redacted(self, tmp_path):
        """Scrubbing an author's prose is its own corruption. Nothing here
        touches dist/, which is why SEC-1.4 refuses a premise carrying a
        credential at the door instead."""
        import inspect
        from novaforge import orchestrator
        from novaforge.export import markdown, pdf

        for module in (markdown, pdf):
            assert "Redactor" not in inspect.getsource(module)
        assert "scrub" in inspect.getsource(orchestrator)
