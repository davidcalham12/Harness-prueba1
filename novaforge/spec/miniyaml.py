"""A YAML parser covering exactly the subset ``specs/flow.yaml`` uses.

`pyproject.toml` promises zero runtime dependencies, and the spec file is the
one thing the program cannot start without. So the subset is parsed here:
block mappings, block sequences, scalars, comments and nesting by indentation.

**Deliberately not supported** - and refused loudly rather than half-parsed:
flow collections (``[a, b]``, ``{a: b}``), anchors and aliases, multi-line
scalars (``|`` and ``>``), multiple documents, and tabs for indentation. Each
raises :class:`YamlError` naming the line, because a spec that parses to
something *almost* right is worse than one that fails.

If PyYAML is installed, :func:`safe_load` defers to it. That makes "is this a
parser bug or a spec bug?" a one-command question::

    pip install pyyaml    # then rerun; if it now works, the bug is here
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["YamlError", "safe_load", "parse"]

try:  # pragma: no cover - depends on the environment
    import yaml as _pyyaml
except ImportError:  # pragma: no cover
    _pyyaml = None

_KEY = re.compile(r"^([A-Za-z_][\w.\-]*)\s*:(?:\s+(.*))?$")
_INT = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?$")


class YamlError(ValueError):
    """The spec file is not the subset this parser accepts."""


def _strip_comment(text: str) -> str:
    """Remove a trailing comment.

    ``#`` only starts a comment at the start of the line or after whitespace,
    so ``outline.md#chapter`` survives intact - which matters, because that is
    a real value in ``flow.yaml``.
    """
    out: list[str] = []
    quote: str | None = None
    for index, ch in enumerate(text):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (index == 0 or text[index - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(text: str, lineno: int) -> Any:
    raw = text.strip()
    if not raw:
        return ""
    if raw[0] in "[{":
        raise YamlError(
            f"line {lineno}: flow collections are not supported by miniyaml; "
            f"use a block sequence or mapping ({raw[:40]!r})"
        )
    if raw[0] in "*&":
        raise YamlError(f"line {lineno}: anchors and aliases are not supported ({raw[:40]!r})")
    if raw in ("|", ">", "|-", ">-"):
        raise YamlError(f"line {lineno}: multi-line scalars are not supported")
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    lowered = raw.lower()
    if lowered in ("null", "~"):
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if _INT.match(raw):
        return int(raw)
    if _FLOAT.match(raw):
        return float(raw)
    return raw


def _tokenise(text: str) -> list[tuple[int, str, int]]:
    """``(indent, content, lineno)`` for every line that carries content."""
    rows: list[tuple[int, str, int]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if raw.strip() in ("---", "..."):
            if raw.strip() == "---" and not rows:
                continue  # a leading document marker is harmless
            raise YamlError(f"line {lineno}: multiple documents are not supported")
        stripped = _strip_comment(raw)
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        if "\t" in raw[:indent + 1]:
            raise YamlError(f"line {lineno}: tab used for indentation; use spaces")
        rows.append((indent, stripped.strip(), lineno))
    return rows


def _parse_node(rows: list[tuple[int, str, int]], i: int, indent: int) -> tuple[Any, int]:
    if i >= len(rows):
        return None, i
    row_indent, content, _ = rows[i]
    if row_indent < indent:
        return None, i
    if content == "-" or content.startswith("- "):
        return _parse_sequence(rows, i, row_indent)
    return _parse_mapping(rows, i, row_indent)


def _parse_sequence(rows: list[tuple[int, str, int]], i: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    while i < len(rows):
        row_indent, content, lineno = rows[i]
        if row_indent < indent:
            break
        if row_indent > indent:
            raise YamlError(f"line {lineno}: unexpected indentation inside a sequence")
        if not (content == "-" or content.startswith("- ")):
            break
        inner = content[1:].lstrip()
        inner_indent = indent + (len(content) - len(inner))
        if not inner:
            # `-` alone: the item is the indented block beneath it.
            value, i = _parse_node(rows, i + 1, indent + 1)
            items.append(value)
            continue
        if _KEY.match(inner):
            # `- key: value` starts a mapping whose later keys sit at inner_indent.
            rows[i] = (inner_indent, inner, lineno)
            value, i = _parse_mapping(rows, i, inner_indent)
            items.append(value)
            continue
        items.append(_scalar(inner, lineno))
        i += 1
    return items, i


def _parse_mapping(rows: list[tuple[int, str, int]], i: int, indent: int) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while i < len(rows):
        row_indent, content, lineno = rows[i]
        if row_indent < indent:
            break
        if row_indent > indent:
            raise YamlError(f"line {lineno}: unexpected indentation inside a mapping")
        if content == "-" or content.startswith("- "):
            break
        match = _KEY.match(content)
        if not match:
            raise YamlError(f"line {lineno}: expected 'key: value', got {content[:60]!r}")
        key, inline = match.group(1), match.group(2)
        if key in mapping:
            raise YamlError(f"line {lineno}: duplicate key {key!r}")
        if inline is not None and inline.strip():
            mapping[key] = _scalar(inline, lineno)
            i += 1
            continue
        # No inline value: the value is the block beneath, if it is deeper.
        nxt = i + 1
        if nxt < len(rows) and rows[nxt][0] > row_indent:
            mapping[key], i = _parse_node(rows, nxt, rows[nxt][0])
        elif nxt < len(rows) and rows[nxt][0] == row_indent and rows[nxt][1].startswith("- "):
            # A sequence may sit at the same indent as its key.
            mapping[key], i = _parse_sequence(rows, nxt, row_indent)
        else:
            mapping[key] = None
            i = nxt
    return mapping, i


def parse(text: str) -> Any:
    """Parse with the built-in parser, whether or not PyYAML is installed."""
    rows = _tokenise(text)
    if not rows:
        return None
    value, index = _parse_node(rows, 0, rows[0][0])
    if index < len(rows):
        raise YamlError(f"line {rows[index][2]}: trailing content the parser could not place")
    return value


def safe_load(text: str) -> Any:
    """Parse ``text``. Defers to PyYAML when it is importable (see module doc)."""
    if _pyyaml is not None:  # pragma: no cover - depends on the environment
        return _pyyaml.safe_load(text)
    return parse(text)
