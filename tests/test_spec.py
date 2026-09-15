"""Parsing and specialising ``specs/flow.yaml``.

Two separate claims are under test:

* :class:`TestMiniYaml` - the built-in parser reads the subset the spec uses,
  and *refuses* what it does not support instead of half-parsing it. A spec
  that parses to something almost right is worse than one that fails.
* :class:`TestApplyConfig` - the spec owns structure, the config owns numbers,
  and every value the config moved is recorded.
"""

from __future__ import annotations

import pytest

from novaforge.config import load_config, package_root
from novaforge.security.prompting import BIBLE_WRITERS
from novaforge.spec.flow import SpecError, load_flow, parse_flow
from novaforge.spec.miniyaml import YamlError, parse

FLOW_PATH = package_root() / "specs" / "flow.yaml"


class TestMiniYaml:
    def test_reads_the_real_spec(self):
        data = parse(FLOW_PATH.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert len(data["stages"]) == 6

    def test_scalars(self):
        data = parse("i: 1\nf: 1.5\nt: true\nf2: false\nn: null\ns: hello\nq: \"a: b\"\n")
        assert data == {"i": 1, "f": 1.5, "t": True, "f2": False,
                        "n": None, "s": "hello", "q": "a: b"}

    def test_a_hash_inside_a_value_is_not_a_comment(self):
        """``outline.md#chapter`` is a real value in flow.yaml."""
        assert parse("k:\n  - outline.md#chapter\n")["k"] == ["outline.md#chapter"]

    def test_a_hash_after_whitespace_is_a_comment(self):
        assert parse("k: value  # trailing\n")["k"] == "value"

    def test_nested_sequences_of_mappings(self):
        data = parse("stages:\n  - id: A\n    n: 1\n  - id: B\n    n: 2\n")
        assert data["stages"] == [{"id": "A", "n": 1}, {"id": "B", "n": 2}]

    def test_a_null_value_is_none_not_the_string(self):
        assert parse("gate: null\n")["gate"] is None

    @pytest.mark.parametrize("text,reason", [
        ("k: [a, b]\n", "flow sequence"),
        ("k: {a: 1}\n", "flow mapping"),
        ("k: &anchor v\n", "anchor"),
        ("k: |\n  text\n", "multi-line scalar"),
        ("a: 1\n---\nb: 2\n", "second document"),
        ("k:\n\tv: 1\n", "tab indentation"),
    ])
    def test_unsupported_syntax_is_refused_not_half_parsed(self, text, reason):
        with pytest.raises(YamlError):
            parse(text)

    def test_duplicate_keys_are_refused(self):
        with pytest.raises(YamlError):
            parse("k: 1\nk: 2\n")

    def test_errors_name_the_line(self):
        with pytest.raises(YamlError, match="line 2"):
            parse("a: 1\nb: [1]\n")


class TestFlowStructure:
    def test_the_six_stages_in_order(self, flow):
        assert [s.id for s in flow] == [f"FLOW-{i}" for i in range(1, 7)]

    def test_every_stage_names_an_implementable_kind(self, flow):
        from novaforge.stages import IMPLEMENTATIONS
        for stage in flow:
            assert stage.impl in IMPLEMENTATIONS, stage.id

    def test_only_flow_4_has_a_gate(self, flow):
        gated = [s.id for s in flow if s.gate is not None]
        assert gated == ["FLOW-4"]

    def test_bible_authority_matches_the_code(self, flow):
        """SEC-4.3: the spec and security.prompting must agree, or the run
        refuses to start rather than picking one."""
        assert flow.bible_writers == BIBLE_WRITERS
        assert flow.bible_writers == {"worldbuilder", "character_architect"}

    def test_flow_4_forbids_prior_chapter_prose(self, flow):
        assert flow.by_id("FLOW-4").context_policy["forbid_prior_chapter_prose"] is True

    def test_by_id_raises_for_an_unknown_stage(self, flow):
        with pytest.raises(KeyError):
            flow.by_id("FLOW-99")

    def test_a_missing_spec_file_does_not_fall_back_to_a_default(self, tmp_path):
        """The spec is data the program executes. There is no built-in pipeline."""
        with pytest.raises(SpecError, match="not found"):
            load_flow(tmp_path / "absent.yaml")


class TestSpecValidation:
    def test_an_unsupported_version_is_refused(self):
        with pytest.raises(SpecError, match="version"):
            parse_flow("version: 2\nstages:\n  - id: A\n    name: a\n"
                       "    impl: outline\n    agent: x\n")

    def test_a_stage_missing_a_required_key_is_refused(self):
        with pytest.raises(SpecError, match="agent"):
            parse_flow("version: 1\nstages:\n  - id: A\n    name: a\n    impl: outline\n")

    def test_duplicate_stage_ids_are_refused(self):
        text = ("version: 1\nstages:\n"
                "  - id: A\n    name: a\n    impl: outline\n    agent: x\n"
                "  - id: A\n    name: b\n    impl: outline\n    agent: y\n")
        with pytest.raises(SpecError, match="duplicate"):
            parse_flow(text)

    def test_an_unknown_on_fail_is_refused(self):
        text = ("version: 1\nstages:\n  - id: A\n    name: a\n    impl: outline\n"
                "    agent: x\n    on_fail: explode\n")
        with pytest.raises(SpecError, match="on_fail"):
            parse_flow(text)

    def test_a_gate_with_no_critics_is_refused(self):
        """It would pass everything."""
        text = ("version: 1\nstages:\n  - id: A\n    name: a\n    impl: outline\n"
                "    agent: x\n    gate:\n      threshold: 8\n")
        with pytest.raises(SpecError, match="critics"):
            parse_flow(text)


class TestApplyConfig:
    def test_the_config_supplies_the_gate_numbers(self, flow, config):
        """CFG-9 — the spec owns structure, the config owns numbers."""
        gate = flow.by_id("FLOW-4").gate
        assert list(gate.critics) == config.get("quality_gate.critics")
        assert gate.threshold == config.get("quality_gate.threshold")
        assert gate.aggregate == config.get("quality_gate.aggregate")

    def test_max_revisions_counts_rewrites_and_max_iterations_counts_drafts(self, flow, config):
        """One first draft plus `max_revisions` rewrites."""
        assert flow.by_id("FLOW-4").gate.max_iterations == \
            config.get("quality_gate.max_revisions") + 1

    def test_changing_the_threshold_in_config_changes_the_spec(self):
        cfg = load_config(profile="tiny", overrides={"quality_gate": {"threshold": 3}})
        assert load_flow(FLOW_PATH, config=cfg).by_id("FLOW-4").gate.threshold == 3

    def test_substitutions_are_recorded(self, flow):
        """The spec on disk is not quite what ran, and the audit log says so."""
        keys = {s["key"] for s in flow.substitutions}
        assert "context_policy.max_summary_words" in keys
        for row in flow.substitutions:
            assert row["spec_value"] != row["config_value"]
            assert row["stage"] == "FLOW-4"

    def test_the_config_cannot_add_a_gate_to_an_ungated_stage(self):
        """CFG-9 — the config says how hard the gate is, never whether there
        is one. That is a structural change made from the wrong file."""
        cfg = load_config(profile="tiny", overrides={"quality_gate": {"threshold": 10}})
        spec = load_flow(FLOW_PATH, config=cfg)
        assert [s.id for s in spec if s.gate is not None] == ["FLOW-4"]

    def test_structure_is_untouched_by_config(self, flow):
        plain = load_flow(FLOW_PATH)
        assert [s.id for s in flow] == [s.id for s in plain]
        assert [s.impl for s in flow] == [s.impl for s in plain]
        assert flow.bible_writers == plain.bible_writers
