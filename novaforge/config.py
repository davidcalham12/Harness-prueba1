"""CFG-1 - loading and layering the configuration.

Four layers, each one overlaying the last::

    config/novel.config.json     the complete, authoritative default
    config/profiles/<name>.json  a partial: states what it changes, nothing else
    --config <path>              an operator's partial overlay
    CLI flags                    the narrowest layer, one key at a time

The merge is recursive, so a profile that sets ``outputs.pdf.page_size`` keeps
the base's ``outputs.pdf.margins_mm``. That is the difference between an
overlay and a replacement, and getting it wrong is how a profile silently drops
half the PDF settings.

**No number in this file.** CFG-5.1 forbids duplicating a config value as a
Python literal: if the loader carried its own default for, say,
``max_summary_words``, there would be two answers to the question and the JSON
would only sometimes be the real one. Missing keys raise instead.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    "ConfigError",
    "Config",
    "config_hash",
    "deep_merge",
    "load_config",
    "package_root",
]


class ConfigError(ValueError):
    """The configuration is missing, malformed, or missing a required key."""


def package_root() -> Path:
    """The repository root - the parent of the ``novaforge`` package.

    ``config/`` and ``specs/`` are data the running program reads, not
    documentation. The loaders refuse to fall back to built-in defaults, so an
    installed copy without them fails loudly at start rather than quietly
    running a different novel.
    """
    return Path(__file__).resolve().parent.parent


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively overlay ``overlay`` onto ``base``.

    Dicts merge; everything else replaces. A list replaces wholesale on
    purpose - a profile that sets ``outputs.formats`` to ``["markdown"]`` means
    *only* markdown, not markdown appended to the base's list.
    """
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _strip_comments(data: Any) -> Any:
    """Drop comment keys. They document the file; they are not settings, and
    leaving them in would change the config hash for a doc edit (CFG-8).

    Any key beginning ``_comment`` counts, not just the exact name. A file with
    two things to explain needs two keys, and ``_comment_observability`` is a
    comment by every reading except a literal string comparison.
    """
    if isinstance(data, Mapping):
        return {k: _strip_comments(v) for k, v in data.items()
                if not str(k).startswith("_comment")}
    if isinstance(data, list):
        return [_strip_comments(v) for v in data]
    return data


def _read_json(path: Path, *, what: str) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"{what} not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{what} is not valid JSON ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{what} must be a JSON object, got {type(data).__name__}")
    return data


def _same_file(a: Path, b: Path) -> bool:
    """True if two paths name the same file on disk.

    Compared by ``samefile`` rather than by string, so ``./config/x.json`` and
    an absolute path to the same file are recognised as one layer.
    """
    try:
        return a.exists() and b.exists() and a.samefile(b)
    except OSError:
        return False


def config_hash(data: Mapping[str, Any]) -> str:
    """A stable 12-hex-digit fingerprint of the resolved config.

    Canonical JSON - sorted keys, no whitespace - so the same settings hash the
    same on any machine. Every audit row carries this, which is what makes
    "these two runs differed only in the config" a checkable statement.
    """
    canonical = json.dumps(_strip_comments(data), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


class Config:
    """The resolved configuration. Read-only, and it refuses to guess.

    Access is by dotted path::

        config.get("novel.words_per_chapter.target")   # raises if absent
        config.get("engine.seed", default=0)           # explicit fallback

    The raising default is the point: a typo in a key name becomes an error at
    the first read instead of a silently wrong novel length.
    """

    _MISSING = object()

    def __init__(self, data: Mapping[str, Any], *, sources: Iterable[str] = ()) -> None:
        self._data = _strip_comments(dict(data))
        self._sources = tuple(sources)
        self._hash = config_hash(self._data)

    @property
    def data(self) -> dict[str, Any]:
        """A deep copy. The config is not a mutable scratchpad."""
        return json.loads(json.dumps(self._data))

    @property
    def hash(self) -> str:
        return self._hash

    @property
    def sources(self) -> tuple[str, ...]:
        """The layers that produced this config, base first. Recorded in the
        snapshot so a run says where each value came from."""
        return self._sources

    def get(self, path: str, default: Any = _MISSING) -> Any:
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, Mapping) or part not in node:
                if default is Config._MISSING:
                    raise ConfigError(
                        f"missing config key {path!r} "
                        f"(layers: {', '.join(self._sources) or 'none'})"
                    )
                return default
            node = node[part]
        return node

    def section(self, path: str) -> dict[str, Any]:
        value = self.get(path)
        if not isinstance(value, Mapping):
            raise ConfigError(f"config key {path!r} is not a section")
        return dict(value)

    def with_overlay(self, overlay: Mapping[str, Any], *, source: str) -> "Config":
        if not overlay:
            return self
        return Config(deep_merge(self._data, overlay), sources=self._sources + (source,))

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"Config(hash={self._hash}, layers={list(self._sources)})"


def load_config(
    *,
    profile: str | None = None,
    overlay_path: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    root: str | Path | None = None,
) -> Config:
    """Resolve the config from its layers, base first.

    ``overrides`` is the CLI layer, already shaped like the config tree.
    """
    base_dir = Path(root) if root is not None else package_root()
    config_dir = base_dir / "config"

    base_path = config_dir / "novel.config.json"
    data = _read_json(base_path, what="base config")
    sources = [f"config/novel.config.json"]

    if profile:
        profile_path = config_dir / "profiles" / f"{profile}.json"
        if not profile_path.exists():
            available = sorted(p.stem for p in (config_dir / "profiles").glob("*.json"))
            raise ConfigError(
                f"unknown profile {profile!r}; available: {', '.join(available) or 'none'}"
            )
        data = deep_merge(data, _read_json(profile_path, what=f"profile {profile!r}"))
        data["profile"] = profile
        sources.append(f"config/profiles/{profile}.json")

    if overlay_path:
        overlay_file = Path(overlay_path)
        overlay = _read_json(overlay_file, what="config overlay")
        if _same_file(overlay_file, base_path):
            # Passing the packaged base to --config is a no-op: it is already
            # the bottom layer. Re-merging it would be worse than pointless -
            # layered on top of a profile it would silently restore the base's
            # values and undo the profile, so a run asked for as `--profile
            # tiny --config config/novel.config.json` would quietly be twelve
            # chapters. The layer is recorded and skipped.
            sources.append(f"{overlay_file.name} (packaged base, already applied)")
        else:
            data = deep_merge(data, overlay)
            sources.append(str(overlay_file).replace("\\", "/"))

    if overrides:
        data = deep_merge(data, overrides)
        sources.append("cli")

    return Config(data, sources=sources)
