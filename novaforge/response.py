"""Reading a model's answer, which is not the same as reading its text.

A model asked for a chapter returns a chapter *and*, often, a sentence either
side of it: "Certainly. Below is the chapter." before, "Let me know if you'd
like me to adjust the tone." after, and sometimes the whole thing inside a
```markdown fence. None of that is misbehaviour - it is the normal spread of a
system that was asked for Markdown and given latitude - and the prompts in
`.claude/skills/` ask for none of it.

Left alone it ends up in `dist/book.md`. That is not a cosmetic problem: it is
published prose the author never wrote, and the Length Critic counts it, so a
chapter can clear its word band on the strength of an apology.

**The split here is deliberate.** Two of these are mechanical and are removed;
the third is a judgement and is reported instead.

* A fence around the *entire* answer has exactly one meaning, so it is
  unwrapped.
* Content before the first heading, for a kind whose prompt asks it to open
  with one, cannot be the content. It is dropped.
* A trailing sentence addressed to the operator *looks* like chatter and might
  be a line of dialogue. It is reported as a finding, so the quality gate asks
  for the chapter again rather than this module quietly editing prose.

That last one is the same reasoning as SEC-4.5, where injection attempts are
logged and never deleted: a program that silently rewrites what an author wrote
is a program you cannot trust with what an author wrote.
"""

from __future__ import annotations

import re

__all__ = [
    "CHATTER",
    "HEADING_KINDS",
    "clean_response",
    "find_chatter",
    "strip_chatter",
    "trim_to_first_heading",
    "unwrap_code_fence",
]

# The task kinds whose SKILL.md tells the agent to open with a heading.
# For these, anything before the first one is the model introducing itself.
# `summary`, `style` and `synopsis` are prose with no heading and are not
# trimmed - there would be nothing left.
HEADING_KINDS = frozenset({"world", "characters", "timeline", "mysteries",
                           "outline", "chapter"})

_FENCE = re.compile(
    r"\A\s*```[a-zA-Z0-9_+-]*\s*\n(?P<body>.*?)\n?\s*```\s*\Z", re.S)

# Phrases that address the operator rather than the reader. Matched only at the
# very start or the very end of an answer: "Let me know" inside a chapter is
# dialogue, and the same words in a trailing paragraph are not.
CHATTER = (
    ("offer-to-revise", re.compile(
        r"(?i)\b(let me know if|happy to (expand|adjust|revise)|"
        r"i can (expand|adjust|revise|lengthen)|say the word if|"
        r"would you like me to)\b")),
    ("self-description", re.compile(
        r"(?i)^\s*(certainly|sure|of course|here(?:'s| is| are)\b|"
        r"i(?:'ve| have) (written|put together|drafted|prepared)|"
        r"below is|the following is)\b")),
    ("meta-commentary", re.compile(
        r"(?i)\b(as requested|per your instructions|i kept this|"
        r"i('ve| have) aimed for|this (chapter|section) (is|comes in) at)\b")),
)


def unwrap_code_fence(text: str) -> str:
    """Remove a fence that wraps the whole answer, and only that.

    A fence around *part* of an answer is content - a model quoting a manifest,
    say - and is left alone. Only a fence with nothing outside it can be
    packaging.
    """
    match = _FENCE.match(text or "")
    return match.group("body") if match else text


def trim_to_first_heading(text: str, *, required: bool = False) -> str:
    """Drop anything before the first ATX heading.

    For a kind whose prompt asks it to open with a heading, whatever precedes
    that heading is not the content - it is the model introducing itself.

    ``required=False`` returns the text unchanged when there is no heading at
    all, because an answer with no heading may still be the answer; it is the
    parsers' job to say otherwise.
    """
    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            return "\n".join(lines[index:])
    return "" if required else text


def find_chatter(text: str, *, window: int = 2) -> list[dict[str, str]]:
    """Report sentences addressed to the operator, at either end of the answer.

    Only the first and last ``window`` paragraphs are examined. The same words
    in the middle of a chapter are prose, and a module that could not tell the
    difference would be a module that edits dialogue.

    Never modifies ``text``.
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    if not blocks:
        return []
    edges = blocks[:window] + blocks[-window:] if len(blocks) > window else blocks
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for block in edges:
        if block.lstrip().startswith("#"):
            continue
        for kind, pattern in CHATTER:
            match = pattern.search(block)
            if match and block not in seen:
                seen.add(block)
                found.append({
                    "kind": kind,
                    "quote": " ".join(block.split())[:160],
                })
                break
    return found


def strip_chatter(text: str, *, window: int = 2) -> tuple[str, list[dict[str, str]]]:
    """Remove operator-facing paragraphs from either end. Returns what was cut.

    **Used in one place only** — the synopsis, which has no gate behind it and
    is marketing copy rather than authored prose. A chapter never goes through
    this: there the gate asks the writer for it again, because "let me know if
    you need anything else" is chatter at the end of a chapter and dialogue in
    the middle of one, and this function cannot tell the difference well enough
    to be trusted with a novel.

    Whole paragraphs are dropped, never edited, and the caller is handed the
    list so that what was removed can be reported rather than done quietly.
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    if not blocks:
        return text, []

    removed: list[dict[str, str]] = []
    keep = list(blocks)
    for where, index in (("start", 0), ("end", -1)):
        for _ in range(window):
            if not keep or not find_chatter(keep[index], window=1):
                break
            removed.append({"where": where,
                            "quote": " ".join(keep[index].split())[:160]})
            keep.pop(index)
    if not keep:
        return text, []  # it was chatter all the way down; leave it visible
    return "\n\n".join(keep) + "\n", removed


def clean_response(text: str, *, expect_heading: bool = False) -> str:
    """The mechanical half: unwrap a whole-answer fence, then trim a preamble.

    Chatter is *not* removed here. :func:`find_chatter` reports it and the
    quality gate acts on it, so nothing in this program edits an author's prose
    on a guess.
    """
    out = unwrap_code_fence(text or "")
    if expect_heading:
        out = trim_to_first_heading(out)
    return out.strip() + "\n" if out.strip() else ""
