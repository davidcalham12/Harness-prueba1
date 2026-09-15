"""CFG-1 - the config layers.

The property being defended is that a *partial* profile is an overlay and not a
replacement. A profile that sets ``outputs.pdf.page_size`` and thereby dropped
the base's ``margins_mm`` would produce a PDF with no margins and no error, so
the recursion is tested per layer rather than only on the final result.
"""

from __future__ import annotations

import json

import pytest

from novaforge.config import Config, ConfigError, config_hash, deep_merge, load_config

PROFILES = ["tiny", "small", "medium", "full"]


class TestDeepMerge:
    def test_nested_dicts_merge_rather_than_replace(self):
        base = {"a": {"x": 1, "y": 2}}
        assert deep_merge(base, {"a": {"y": 9}}) == {"a": {"x": 1, "y": 9}}

    def test_lists_replace_wholesale(self):
        """A profile setting outputs.formats to ['markdown'] means *only*
        markdown, not markdown appended to the base's list."""
        assert deep_merge({"f": ["a", "b"]}, {"f": ["a"]}) == {"f": ["a"]}

    def test_the_base_is_not_mutated(self):
        base = {"a": {"x": 1}}
        deep_merge(base, {"a": {"x": 2}})
        assert base == {"a": {"x": 1}}


class TestLoading:
    def test_base_alone_loads(self):
        cfg = load_config()
        assert cfg.get("novel.chapters") == 12
        assert cfg.sources == ("config/novel.config.json",)

    @pytest.mark.parametrize("profile", PROFILES)
    def test_every_profile_loads_and_records_its_layers(self, profile):
        cfg = load_config(profile=profile)
        assert cfg.get("profile") == profile
        assert cfg.sources[-1] == f"config/profiles/{profile}.json"

    def test_tiny_is_three_short_chapters(self):
        cfg = load_config(profile="tiny")
        assert cfg.get("novel.chapters") == 3
        assert cfg.get("novel.words_per_chapter.max") == 550
        assert cfg.get("novel.chars_per_line.max") == 64

    @pytest.mark.parametrize("profile", PROFILES)
    def test_a_profile_inherits_what_it_does_not_state(self, profile):
        """The overlay property, checked on the settings most likely to be
        silently lost."""
        base, cfg = load_config(), load_config(profile=profile)
        assert cfg.get("outputs.pdf.margins_mm") == base.get("outputs.pdf.margins_mm")
        assert cfg.get("quality_gate") == base.get("quality_gate")
        assert cfg.get("bible") == base.get("bible")
        assert cfg.get("outputs.formats") == base.get("outputs.formats")

    def test_only_tiny_changes_the_page_size(self):
        assert load_config(profile="tiny").get("outputs.pdf.page_size") == "a5"
        for profile in ("small", "medium", "full"):
            assert load_config(profile=profile).get("outputs.pdf.page_size") == "a4"

    def test_cli_overrides_beat_the_profile(self):
        cfg = load_config(profile="tiny", overrides={"novel": {"chapters": 2}})
        assert cfg.get("novel.chapters") == 2
        assert cfg.get("novel.words_per_chapter.max") == 550  # still tiny's
        assert cfg.sources[-1] == "cli"

    def test_an_overlay_file_layers_on_top(self, tmp_path):
        overlay = tmp_path / "over.json"
        overlay.write_text(json.dumps({"novel": {"chapters": 4}}), encoding="utf-8")
        cfg = load_config(profile="tiny", overlay_path=overlay)
        assert cfg.get("novel.chapters") == 4

    def test_passing_the_packaged_base_to_config_is_a_no_op(self):
        """RUNBOOK §0 says so, because the base is already the bottom layer."""
        from novaforge.config import package_root
        plain = load_config(profile="tiny")
        doubled = load_config(profile="tiny",
                              overlay_path=package_root() / "config" / "novel.config.json")
        assert doubled.hash == plain.hash

    def test_unknown_profile_names_the_available_ones(self):
        with pytest.raises(ConfigError) as exc:
            load_config(profile="enormous")
        assert "tiny" in str(exc.value)


class TestAccess:
    def test_a_missing_key_raises_rather_than_guessing(self):
        """CFG-5.1: a typo must fail at the first read, not produce a silently
        wrong novel."""
        with pytest.raises(ConfigError):
            load_config().get("novel.chpaters")

    def test_an_explicit_default_is_honoured(self):
        assert load_config().get("novel.nope", default=7) == 7

    def test_data_is_a_copy(self):
        cfg = load_config()
        cfg.data["novel"]["chapters"] = 999
        assert cfg.get("novel.chapters") == 12


class TestHash:
    def test_the_same_settings_hash_the_same(self):
        assert load_config(profile="tiny").hash == load_config(profile="tiny").hash

    def test_different_settings_hash_differently(self):
        assert load_config(profile="tiny").hash != load_config(profile="small").hash

    def test_key_order_does_not_change_the_hash(self):
        assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})

    def test_comments_do_not_change_the_hash(self):
        """A doc edit must not invalidate every audit row."""
        assert config_hash({"a": 1}) == config_hash({"a": 1, "_comment": "why"})

    def test_the_hash_is_short_and_hex(self):
        value = load_config(profile="tiny").hash
        assert len(value) == 12 and int(value, 16) >= 0
