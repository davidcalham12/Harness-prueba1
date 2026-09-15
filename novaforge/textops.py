"""Text measurement and parsing, with no knowledge of the pipeline.

Everything here is pure: text in, text or numbers out. The critics measure with
these functions and the exporters wrap with them, so "550 words" means the same
thing to the Length Critic, to the Markdown writer and to the test suite.

Parsing is deliberately forgiving. It reads Markdown that a *model* wrote, so
it recognises the shapes the Bible prompts ask for and ignores everything else
rather than raising - a malformed Bible is a quality problem for the critics to
find, not a crash.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

__all__ = [
    "Character",
    "chapter_body",
    "count_lines",
    "count_paragraphs",
    "count_sentences",
    "count_words",
    "heading",
    "paragraphs",
    "parse_characters",
    "parse_outline",
    "parse_world_rules",
    "slugify",
    "wrap_paragraph",
    "wrap_text",
]

_SENTENCE_END = re.compile(r"[.!?]+[\"')\]]*(?:\s|$)")
_BULLET = re.compile(r"^\s*[-*+]\s+")
_BOLD_NAME = re.compile(r"\*\*(.+?)\*\*")


@dataclass(frozen=True)
class Character:
    """One cast member, as fixed by the Character Architect.

    ``name`` is canonical: the Continuity Critic compares chapter prose against
    it, so a drifted spelling in a draft becomes a finding rather than a new
    character.
    """

    name: str
    role: str = ""
    traits: tuple[str, ...] = field(default_factory=tuple)

    @property
    def surname(self) -> str:
        return self.name.split()[-1] if self.name.split() else ""


# -- measurement ---------------------------------------------------------


def count_words(text: str) -> int:
    return len((text or "").split())


def count_lines(text: str) -> int:
    """Non-empty lines. Blank separators are layout, not content."""
    return len([line for line in (text or "").splitlines() if line.strip()])


def paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", text or "")
    return [block.strip() for block in blocks if block.strip()]


def count_paragraphs(text: str) -> int:
    return len(paragraphs(text))


def count_sentences(text: str) -> int:
    hits = len(_SENTENCE_END.findall(text or ""))
    # Trailing fragment with no terminator still reads as a sentence.
    if (text or "").strip() and not _SENTENCE_END.search((text or "").strip()[-3:]):
        hits += 1
    return max(hits, 1) if (text or "").strip() else 0


# -- structure -----------------------------------------------------------


def heading(text: str) -> str:
    """The first ATX heading, without its hashes. ``""`` if there is none."""
    for line in (text or "").splitlines():
        if line.lstrip().startswith("#"):
            return line.lstrip("#").strip()
    return ""


def chapter_body(text: str) -> str:
    """The prose only, with headings dropped.

    :func:`novaforge.context.assert_no_prior_prose` compares against this, so a
    shared chapter *title* never counts as leaked prose - only the writing does.
    """
    return "\n".join(
        line for line in (text or "").splitlines() if not line.lstrip().startswith("#")
    )


# -- wrapping ------------------------------------------------------------


def wrap_paragraph(text: str, width: int) -> list[str]:
    """Greedy wrap of one paragraph. Words longer than ``width`` get their own
    line rather than being broken - a hyphenated compound is still one word."""
    limit = max(8, int(width))
    lines: list[str] = []
    current = ""
    for word in (text or "").split():
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= limit:
            current = current + " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def wrap_text(text: str, width: int) -> str:
    """Wrap prose, preserving the blank line between paragraphs and passing
    headings through untouched (a wrapped heading is a broken heading)."""
    out: list[str] = []
    for block in paragraphs(text):
        if block.lstrip().startswith("#"):
            out.append(block.strip())
        else:
            flat = " ".join(block.split())
            out.extend(wrap_paragraph(flat, width))
        out.append("")
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


# -- parsing the Bible ---------------------------------------------------


def parse_characters(markdown: str) -> tuple[Character, ...]:
    """Read ``bible/characters.md``.

    Recognises the shape the Character Architect is asked to produce::

        - **Mara Kassab** — salvage pilot; steady, secretive

    The name is whatever is bold. Everything after the first dash is the role,
    and a trailing semicolon-separated clause becomes traits.
    """
    found: list[Character] = []
    seen: set[str] = set()
    for line in (markdown or "").splitlines():
        if not _BULLET.match(line):
            continue
        match = _BOLD_NAME.search(line)
        if not match:
            continue
        name = " ".join(match.group(1).split())
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        rest = line[match.end():].lstrip(" \t—-–:").strip()
        role, _, trailing = rest.partition(";")
        traits = tuple(t.strip() for t in trailing.split(",") if t.strip())
        found.append(Character(name=name, role=role.strip(), traits=traits))
    return tuple(found)


def parse_world_rules(markdown: str) -> tuple[str, ...]:
    """Read the rules out of ``bible/world.md``.

    Only bullets under a heading whose text contains "rule" count. A world file
    is mostly prose, and the Science Auditor must not audit against a bullet
    that was describing a faction.
    """
    rules: list[str] = []
    in_rules = False
    for line in (markdown or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            in_rules = "rule" in stripped.lower()
            continue
        if in_rules and _BULLET.match(line):
            rule = _BULLET.sub("", line).strip()
            rule = _BOLD_NAME.sub(r"\1", rule)
            if rule:
                rules.append(rule)
    return tuple(rules)


_CHAPTER_HEADING = re.compile(r"^#{2,4}\s*chapter\s+(\d+)\s*[—\-:–]?\s*(.*)$", re.IGNORECASE)
_FIELD = re.compile(r"^\s*[-*+]\s*\*\*(?P<key>[^:*]+):?\*\*:?\s*(?P<value>.*)$")


def parse_outline(markdown: str) -> tuple[dict[str, object], ...]:
    """Read ``outline.md`` into one dict per chapter.

    Returns plain dicts rather than :class:`~novaforge.domain.models.ChapterPlan`
    so that this module stays free of domain imports - the outline stage does
    the conversion, and gets to decide what a malformed row means.

    Tolerant by design: a missing POV or tension yields a default rather than
    an exception, because a model wrote this file and a thin outline entry is
    a quality problem, not a crash.
    """
    plans: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    in_beats = False

    for line in (markdown or "").splitlines():
        match = _CHAPTER_HEADING.match(line.strip())
        if match:
            if current is not None:
                plans.append(current)
            current = {
                "number": int(match.group(1)),
                "title": match.group(2).strip() or f"Chapter {match.group(1)}",
                "pov": "",
                "tension": 5,
                "promise": "",
                "beats": [],
            }
            in_beats = False
            continue
        if current is None:
            continue

        field_match = _FIELD.match(line)
        if field_match:
            key = field_match.group("key").strip().lower()
            value = field_match.group("value").strip()
            if key.startswith("pov"):
                current["pov"] = value
                in_beats = False
            elif key.startswith("tension"):
                digits = re.match(r"(\d+)", value)
                current["tension"] = int(digits.group(1)) if digits else 5
                in_beats = False
            elif key.startswith("promise"):
                current["promise"] = value
                in_beats = False
            elif key.startswith("beat"):
                in_beats = True
                if value:
                    current["beats"].append(value)  # type: ignore[union-attr]
            else:
                in_beats = False
            continue

        if in_beats and _BULLET.match(line):
            beat = _BULLET.sub("", line).strip()
            if beat:
                current["beats"].append(beat)  # type: ignore[union-attr]

    if current is not None:
        plans.append(current)
    return tuple(sorted(plans, key=lambda p: p["number"]))


# -- identifiers ---------------------------------------------------------


def slugify(text: str, *, max_length: int = 48) -> str:
    """A filesystem-safe slug from a premise.

    The result still has to clear ``security.validation.validate_slug`` - this
    produces a candidate, it does not authorise a path.
    """
    normalised = unicodedata.normalize("NFKD", text or "")
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii").lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip("-")
    return cleaned or "untitled"
