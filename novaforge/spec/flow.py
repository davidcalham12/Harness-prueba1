"""Turning ``specs/flow.yaml`` into the objects the orchestrator executes.

The division of ownership, restated because it is the point of the design:

* **The spec owns structure** - which stages exist, their order, their ``impl``,
  which may write the Story Bible, their inputs and outputs.
* **The config owns numbers** - which critics are in the gate, what score
  clears it, how many drafts are allowed.

:func:`apply_config` is where the second overwrites the first. The gate values
written in the YAML are defaults for *reading*; the resolved config replaces
them at load time, and :attr:`FlowSpec.substitutions` records every value that
moved so the audit log can say the spec on disk is not quite what ran.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .miniyaml import YamlError, safe_load

__all__ = ["FlowSpec", "Gate", "SpecError", "Stage", "load_flow"]

_ON_FAIL = ("halt", "accept_with_warnings", "skip")
_AGGREGATE = ("min", "mean")


class SpecError(ValueError):
    """The flow spec is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class Gate:
    """A stage's quality gate. ``None`` on a stage that has none."""

    critics: tuple[str, ...]
    threshold: int
    max_iterations: int
    aggregate: str = "min"

    def __post_init__(self) -> None:
        if not self.critics:
            raise SpecError("a gate with no critics would pass everything")
        if self.max_iterations < 1:
            raise SpecError(f"max_iterations must be >= 1, got {self.max_iterations}")
        if self.aggregate not in _AGGREGATE:
            raise SpecError(f"unknown aggregate {self.aggregate!r}; have {_AGGREGATE}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "critics": list(self.critics),
            "threshold": self.threshold,
            "max_iterations": self.max_iterations,
            "aggregate": self.aggregate,
        }


@dataclass(frozen=True)
class Stage:
    """One stage of the pipeline, exactly as declared."""

    id: str
    name: str
    impl: str
    agent: str
    description: str = ""
    inputs: tuple[str, ...] = field(default_factory=tuple)
    outputs: tuple[str, ...] = field(default_factory=tuple)
    writes_bible: bool = False
    foreach: str | None = None
    gate: Gate | None = None
    on_fail: str = "halt"
    context_policy: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "impl": self.impl,
            "agent": self.agent,
            "writes_bible": self.writes_bible,
            "foreach": self.foreach,
            "gate": self.gate.to_dict() if self.gate else None,
            "on_fail": self.on_fail,
        }


@dataclass(frozen=True)
class FlowSpec:
    """The whole pipeline."""

    version: int
    name: str
    description: str
    stages: tuple[Stage, ...]
    defaults: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""
    substitutions: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def __iter__(self):
        return iter(self.stages)

    def __len__(self) -> int:
        return len(self.stages)

    def by_id(self, stage_id: str) -> Stage:
        for stage in self.stages:
            if stage.id == stage_id:
                return stage
        raise KeyError(f"no stage {stage_id!r} in {self.name}")

    @property
    def agents(self) -> tuple[str, ...]:
        seen: list[str] = []
        for stage in self.stages:
            if stage.agent not in seen:
                seen.append(stage.agent)
        return tuple(seen)

    @property
    def bible_writers(self) -> frozenset[str]:
        """The agents this spec permits to write the Bible.

        Cross-checked against :data:`novaforge.security.prompting.BIBLE_WRITERS`
        at load time: if the spec and the code disagree about authority, the
        run refuses to start rather than picking one (SEC-4.3).
        """
        return frozenset(s.agent for s in self.stages if s.writes_bible)


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def _build_gate(raw: Any, defaults: Mapping[str, Any], where: str) -> Gate | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise SpecError(f"{where}: gate must be a mapping or null")
    try:
        return Gate(
            critics=_as_tuple(raw.get("critics")),
            threshold=int(raw.get("threshold", defaults.get("gate_threshold", 8))),
            max_iterations=int(raw.get("max_iterations", defaults.get("max_iterations", 3))),
            aggregate=str(raw.get("aggregate", defaults.get("aggregate", "min"))),
        )
    except SpecError as exc:
        raise SpecError(f"{where}: {exc}") from exc


def _build_stage(raw: Any, defaults: Mapping[str, Any], index: int) -> Stage:
    if not isinstance(raw, Mapping):
        raise SpecError(f"stage #{index + 1} is not a mapping")
    where = f"stage {raw.get('id', '#' + str(index + 1))}"
    for required in ("id", "name", "impl", "agent"):
        if not raw.get(required):
            raise SpecError(f"{where}: missing required key {required!r}")
    on_fail = str(raw.get("on_fail", defaults.get("on_fail", "halt")))
    if on_fail not in _ON_FAIL:
        raise SpecError(f"{where}: unknown on_fail {on_fail!r}; have {_ON_FAIL}")
    policy = raw.get("context_policy") or {}
    if not isinstance(policy, Mapping):
        raise SpecError(f"{where}: context_policy must be a mapping")
    return Stage(
        id=str(raw["id"]),
        name=str(raw["name"]),
        impl=str(raw["impl"]),
        agent=str(raw["agent"]),
        description=str(raw.get("description", "")),
        inputs=_as_tuple(raw.get("inputs")),
        outputs=_as_tuple(raw.get("outputs")),
        writes_bible=bool(raw.get("writes_bible", False)),
        foreach=str(raw["foreach"]) if raw.get("foreach") else None,
        gate=_build_gate(raw.get("gate"), defaults, where),
        on_fail=on_fail,
        context_policy=dict(policy),
    )


def parse_flow(text: str, *, source: str = "") -> FlowSpec:
    """Parse spec text. Structure only - no config has been applied yet."""
    try:
        data = safe_load(text)
    except YamlError as exc:
        raise SpecError(f"{source or 'flow spec'}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise SpecError(f"{source or 'flow spec'}: top level must be a mapping")

    version = data.get("version")
    if version != 1:
        raise SpecError(f"unsupported spec version {version!r}; this build reads version 1")

    raw_stages = data.get("stages")
    if not isinstance(raw_stages, Sequence) or not raw_stages:
        raise SpecError("spec declares no stages")

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, Mapping):
        raise SpecError("defaults must be a mapping")

    stages = tuple(_build_stage(raw, defaults, i) for i, raw in enumerate(raw_stages))

    seen: set[str] = set()
    for stage in stages:
        if stage.id in seen:
            raise SpecError(f"duplicate stage id {stage.id!r}")
        seen.add(stage.id)

    return FlowSpec(
        version=1,
        name=str(data.get("name", "unnamed")),
        description=str(data.get("description", "")),
        stages=stages,
        defaults=dict(defaults),
        source=source,
    )


def apply_config(spec: FlowSpec, config: Any) -> FlowSpec:
    """Overlay the config's numbers onto the spec's structure.

    Only stages that already declare a gate get one: the config says *how hard*
    the gate is, never *whether there is one*. Adding a gate to a stage the
    spec did not gate would be a structural change made from the wrong file.
    """
    critics = tuple(config.get("quality_gate.critics"))
    threshold = int(config.get("quality_gate.threshold"))
    aggregate = str(config.get("quality_gate.aggregate"))
    # The config counts rewrites; the spec counts drafts. One first draft plus
    # `max_revisions` rewrites is `max_revisions + 1` iterations.
    max_iterations = int(config.get("quality_gate.max_revisions")) + 1

    moved: list[Mapping[str, Any]] = []
    new_stages: list[Stage] = []
    for stage in spec.stages:
        if stage.gate is None:
            new_stages.append(stage)
            continue
        updated = Gate(
            critics=critics,
            threshold=threshold,
            max_iterations=max_iterations,
            aggregate=aggregate,
        )
        for key, before, after in (
            ("critics", stage.gate.critics, updated.critics),
            ("threshold", stage.gate.threshold, updated.threshold),
            ("max_iterations", stage.gate.max_iterations, updated.max_iterations),
            ("aggregate", stage.gate.aggregate, updated.aggregate),
        ):
            if before != after:
                moved.append({
                    "stage": stage.id,
                    "key": f"gate.{key}",
                    "spec_value": list(before) if isinstance(before, tuple) else before,
                    "config_value": list(after) if isinstance(after, tuple) else after,
                })
        policy = dict(stage.context_policy)
        if policy:
            before_words = policy.get("max_summary_words")
            after_words = int(config.get("context.max_summary_words"))
            if before_words != after_words:
                moved.append({
                    "stage": stage.id,
                    "key": "context_policy.max_summary_words",
                    "spec_value": before_words,
                    "config_value": after_words,
                })
            policy["max_summary_words"] = after_words
            policy["forbid_prior_chapter_prose"] = bool(
                config.get("context.forbid_prior_chapter_prose")
            )
        new_stages.append(replace(stage, gate=updated, context_policy=policy))

    on_fail = str(config.get("quality_gate.on_fail"))
    new_stages = [
        replace(s, on_fail=on_fail) if s.gate is not None and s.on_fail != on_fail else s
        for s in new_stages
    ]
    return replace(spec, stages=tuple(new_stages), substitutions=tuple(moved))


def _check_authority(spec: FlowSpec) -> None:
    from ..security.prompting import BIBLE_WRITERS

    declared = spec.bible_writers
    if declared != BIBLE_WRITERS:
        raise SpecError(
            f"spec and code disagree about Bible authority (SEC-4.3): spec says "
            f"{sorted(declared)}, security.prompting says {sorted(BIBLE_WRITERS)}"
        )


def load_flow(path: str | Path, *, config: Any = None) -> FlowSpec:
    """Read, validate and (if ``config`` is given) specialise the flow spec."""
    spec_path = Path(path)
    if not spec_path.exists():
        raise SpecError(
            f"flow spec not found: {spec_path}. The spec is data the program "
            f"executes; there is no built-in fallback pipeline."
        )
    spec = parse_flow(spec_path.read_text(encoding="utf-8"),
                      source=str(spec_path).replace("\\", "/"))
    _check_authority(spec)
    if config is not None:
        spec = apply_config(spec, config)
    return spec
