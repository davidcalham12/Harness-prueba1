"""An engine that returns what a *real* model returns, mess and all.

The mock engine emits exactly the shapes the parsers expect, because the same
person wrote both. That makes it perfect for reproducibility and useless for
finding out whether this harness can read a real model's answer.

A real model, asked for a cast list, will sometimes:

* open with "Here is the cast for your novel:" before the Markdown;
* wrap the whole reply in a ```markdown fence;
* write `- **Mara Kassab** - salvage pilot` with a hyphen where the prompt
  showed an em dash, or `: ` instead;
* use `*` bullets, or a numbered list;
* title a chapter `# Chapter 1: The Cold Lamp`, or `# Chapter One — ...`, or
  `## Chapter 1`;
* close with "Let me know if you'd like me to adjust the tone."

None of that is the model misbehaving. It is the normal spread of a system that
was asked for Markdown and given latitude. This engine applies those variations
on top of the mock's content, deterministically, so the pipeline can be run
against them before a single paid call is made.

It lives in ``tests/`` rather than ``novaforge/`` on purpose: it is a probe for
finding fragility, not something the shipped program should be able to select.
"""

from __future__ import annotations

import random
import re

from novaforge.engines.base import Completion, Request
from novaforge.engines.mock import MockEngine

__all__ = ["MessyEngine", "PERTURBATIONS"]

PREAMBLES = (
    "Here is the {what} for your novel:",
    "Certainly. Below is the {what}.",
    "I've put together the {what} based on the premise and the canon you gave me.",
)

TRAILERS = (
    "Let me know if you'd like me to adjust the tone or add more detail.",
    "Happy to expand any section further.",
    "I kept this tight; say the word if you want it longer.",
)

# Each is a (name, function) pair so a failure can be reported by name rather
# than as "something in the perturbation chain".
PERTURBATIONS = (
    "preamble",
    "trailer",
    "code_fence",
    "hyphen_separator",
    "colon_separator",
    "star_bullets",
    "numbered_list",
    "colon_chapter_title",
    "deeper_headings",
    "spelled_out_number",
    "bold_heading_instead_of_hash",
)


class MessyEngine:
    """Wraps the mock and roughens its output in realistic ways."""

    name = "messy"

    def __init__(self, *, model: str, seed: int = 0, inject_drift: bool = True,
                 only: tuple[str, ...] | None = None) -> None:
        self._inner = MockEngine(model=model, seed=seed, inject_drift=inject_drift)
        self.model = model
        self.seed = seed
        # ``only`` restricts the perturbations applied, so a failing pipeline
        # can be bisected down to the one variation that breaks it.
        self.only = tuple(only) if only is not None else PERTURBATIONS
        self.applied: list[tuple[str, str]] = []

    def complete(self, request: Request) -> Completion:
        completion = self._inner.complete(request)
        # `attempt` is part of the seed because a real model asked the same
        # question twice answers differently, and a simulator that returned
        # the identical mess both times would make any retry look useless.
        rng = random.Random(f"{self.seed}|{request.kind}|"
                            f"{request.task.get('chapter', 0)}|"
                            f"{request.task.get('iteration', 0)}|"
                            f"{request.task.get('attempt', 0)}|"
                            f"{request.task.get('section', '')}")
        text = self._roughen(completion.text, request.kind, rng)
        return Completion(text=text, usage=completion.usage, model=completion.model)

    # -- the variations --------------------------------------------------

    def _use(self, name: str, rng: random.Random, odds: float = 0.5) -> bool:
        return name in self.only and rng.random() < odds

    def _roughen(self, text: str, kind: str, rng: random.Random) -> str:
        what = {"world": "world bible", "characters": "cast",
                "timeline": "timeline", "mysteries": "mysteries",
                "outline": "outline", "chapter": "chapter",
                "synopsis": "synopsis"}.get(kind, "text")

        if self._use("hyphen_separator", rng):
            text = text.replace("** — ", "** - ")
            self._note("hyphen_separator", kind)
        if self._use("colon_separator", rng, 0.3):
            text = text.replace("** — ", "**: ")
            self._note("colon_separator", kind)
        if self._use("star_bullets", rng, 0.4):
            text = re.sub(r"(?m)^- ", "* ", text)
            self._note("star_bullets", kind)
        if self._use("numbered_list", rng, 0.25) and kind == "mysteries":
            lines, n = [], 0
            for line in text.splitlines():
                if line.startswith("- "):
                    n += 1
                    lines.append(f"{n}. " + line[2:])
                else:
                    lines.append(line)
            text = "\n".join(lines)
            self._note("numbered_list", kind)
        if self._use("colon_chapter_title", rng) and kind in ("chapter", "outline"):
            text = re.sub(r"(#+ Chapter \d+) — ", r"\1: ", text)
            self._note("colon_chapter_title", kind)
        if self._use("spelled_out_number", rng, 0.25) and kind == "chapter":
            words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
            text = re.sub(r"(# Chapter )(\d+)",
                          lambda m: m.group(1) + words.get(int(m.group(2)), m.group(2)),
                          text, count=1)
            self._note("spelled_out_number", kind)
        if self._use("deeper_headings", rng, 0.3) and kind in ("world", "chapter"):
            text = re.sub(r"(?m)^## ", "### ", text)
            text = re.sub(r"(?m)^# (?!##)", "## ", text)
            self._note("deeper_headings", kind)
        if self._use("bold_heading_instead_of_hash", rng, 0.25) and kind == "outline":
            text = re.sub(r"(?m)^### (Chapter \d+.*)$", r"**\1**", text)
            self._note("bold_heading_instead_of_hash", kind)
        if self._use("preamble", rng, 0.4):
            text = rng.choice(PREAMBLES).format(what=what) + "\n\n" + text
            self._note("preamble", kind)
        if self._use("trailer", rng, 0.3):
            text = text.rstrip() + "\n\n" + rng.choice(TRAILERS) + "\n"
            self._note("trailer", kind)
        if self._use("code_fence", rng, 0.3):
            text = "```markdown\n" + text.strip() + "\n```"
            self._note("code_fence", kind)
        return text

    def _note(self, name: str, kind: str) -> None:
        self.applied.append((kind, name))
