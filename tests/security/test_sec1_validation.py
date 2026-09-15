"""SEC-1 - input validation.

The property under test throughout is that this module **rejects rather than
coerces**. A slug that is quietly cleaned up is a slug whose final value the
caller never saw, and the directory it names is one they did not choose — so
every test that supplies bad input asserts a raise, never a repaired return.
"""

from __future__ import annotations

import pytest

from novaforge.security.validation import (
    MAX_PREMISE_CHARS,
    MIN_PREMISE_CHARS,
    SLUG_PATTERN,
    ValidationError,
    validate_premise,
    validate_slug,
)
from novaforge.textops import slugify

PREMISE = "A deep-space salvage crew finds a derelict that remembers them"


class TestSlug:
    @pytest.mark.parametrize("slug", [
        "a", "golden-tiny", "run-2", "x" * 64,
        "a-deep-space-salvage-crew-finds-a-derelict-that",
    ])
    def test_acceptable_slugs_pass_through_unchanged(self, slug):
        assert validate_slug(slug) == slug

    @pytest.mark.parametrize("slug,why", [
        ("", "empty"),
        ("MiSlug", "uppercase"),
        ("-leading", "starts with a hyphen"),
        ("trailing-", "ends with a hyphen"),
        ("a--b", "double hyphen"),
        ("has space", "whitespace"),
        (" padded ", "padding"),
        ("../escape", "traversal"),
        ("a/b", "separator"),
        ("a.b", "dot"),
        ("x" * 65, "too long"),
        ("ñandú", "non-ascii"),
    ])
    def test_unacceptable_slugs_raise(self, slug, why):
        with pytest.raises(ValidationError):
            validate_slug(slug)

    @pytest.mark.parametrize("slug", ["con", "nul", "com1", "lpt9", "aux"])
    def test_windows_device_names_are_refused(self, slug):
        """They cannot be a directory on every platform this runs on."""
        with pytest.raises(ValidationError, match="device"):
            validate_slug(slug)

    def test_nothing_is_ever_repaired(self):
        """The distinction this module exists for."""
        for bad in (" padded ", "MiSlug", "trailing-"):
            with pytest.raises(ValidationError):
                validate_slug(bad)

    def test_the_error_says_what_is_accepted(self):
        with pytest.raises(ValidationError, match="lowercase letters"):
            validate_slug("MiSlug")

    def test_a_non_string_is_refused_rather_than_coerced(self):
        with pytest.raises(ValidationError, match="string"):
            validate_slug(42)  # type: ignore[arg-type]

    def test_slugify_and_validate_are_separate_steps(self):
        """`slugify` produces a candidate; this authorises it. Keeping them
        apart means nothing can both clean up and approve in one step."""
        assert validate_slug(slugify(PREMISE))
        assert validate_slug(slugify("Ñandú: ¡vuela!")) == "nandu-vuela"

    @pytest.mark.parametrize("text", ["A B C", "¡¿?!", "x" * 200, "--leading--", ""])
    def test_every_slugify_output_clears_validation(self, text):
        """If these two ever disagreed, a legitimate premise would produce a
        slug the program then refused."""
        assert validate_slug(slugify(text))

    def test_the_pattern_is_the_documented_one(self):
        assert SLUG_PATTERN.pattern == r"^[a-z0-9][a-z0-9-]{0,63}$"


class TestPremise:
    def test_an_ordinary_premise_passes_through_unchanged(self):
        assert validate_premise(PREMISE) == PREMISE

    def test_too_short_is_refused(self):
        with pytest.raises(ValidationError, match="at least"):
            validate_premise("short")

    def test_too_long_is_refused(self):
        with pytest.raises(ValidationError, match="limit"):
            validate_premise("x" * (MAX_PREMISE_CHARS + 1))

    def test_the_boundaries_themselves_are_accepted(self):
        assert validate_premise("x" * MIN_PREMISE_CHARS)
        assert validate_premise("x" * MAX_PREMISE_CHARS)

    @pytest.mark.parametrize("char,name", [
        ("​", "zero-width space"),
        ("‮", "right-to-left override"),
        ("­", "soft hyphen"),
        (chr(0), "null"),
        ("⁠", "word joiner"),
    ])
    def test_invisible_characters_are_refused(self, char, name):
        """SEC-1.2: invisible to a human reviewing the premise, fully visible to
        the model reading it."""
        with pytest.raises(ValidationError, match="invisible"):
            validate_premise(f"A crew finds{char} a derelict aboard")

    def test_the_error_names_the_character_and_its_position(self):
        with pytest.raises(ValidationError, match=r"U\+200B"):
            validate_premise("A crew finds​ a derelict aboard")

    def test_ordinary_punctuation_and_accents_are_fine(self):
        assert validate_premise("Una nave — «la Kassab» — encuentra algo; y recuerda.")

    def test_newlines_and_tabs_are_allowed(self):
        assert validate_premise("A crew finds a derelict.\n\tIt remembers them.")

    @pytest.mark.parametrize("secret", [
        "sk-ant-api03-AAAAAAAAAAAAAAAAAAAA",
        "api_key=hunter2hunter2hunter2",
        "Bearer abcdefghijklmnopqrstuvwxyz",
    ])
    def test_a_premise_carrying_a_credential_is_refused(self, secret):
        """SEC-1.4. The premise is the one input that reaches the Story Bible
        verbatim, and from there the manuscript — which is deliberately *not*
        redacted, because scrubbing an author's prose is its own corruption.
        The door is the only place this can be caught."""
        with pytest.raises(ValidationError, match="credential"):
            validate_premise(f"A crew finds a derelict and the readout says {secret}")

    def test_content_is_not_judged(self):
        """SEC-1.3: NovaForge does not moderate what you ask it to write."""
        assert validate_premise("A grim story about war, betrayal and death.")


class TestInTheCli:
    def test_a_bad_slug_stops_the_run_before_anything_is_written(self, tmp_path,
                                                                monkeypatch):
        from conftest import isolated_root
        from novaforge import cli

        root = isolated_root(tmp_path)
        monkeypatch.setattr(cli, "package_root", lambda: root)
        assert cli.main(["new", PREMISE, "--slug", "Bad Slug", "--engine", "mock",
                         "--profile", "tiny", "--quiet"]) == 2
        assert list((root / "output").iterdir()) == []

    def test_a_bad_premise_stops_the_run(self, tmp_path, monkeypatch, capsys):
        from conftest import isolated_root
        from novaforge import cli

        root = isolated_root(tmp_path)
        monkeypatch.setattr(cli, "package_root", lambda: root)
        assert cli.main(["new", "tiny", "--profile", "tiny", "--engine", "mock",
                         "--quiet"]) == 2
        assert "invalid input" in capsys.readouterr().err
