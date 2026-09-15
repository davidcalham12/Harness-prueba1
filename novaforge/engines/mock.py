"""A deterministic, free engine that produces text of the right *shape*.

It is not trying to write well. It is trying to be a faithful stand-in for the
parts of a real run that the harness depends on: artefacts with the structure
the parsers expect, chapters inside the configured length band, and the same
call-and-usage accounting a paid run produces. That is what lets the whole test
suite - and the committed golden run - exercise the real orchestrator, the real
gate and the real exporters at zero cost.

**The drift is on purpose.** With ``inject_drift``, the first draft of every
even-numbered chapter misspells a canonical surname. The Continuity Critic
catches it, the gate rejects the draft, and the rewrite fixes it. A run where
every chapter passes first time would demonstrate nothing about the gate, so
the mock is built to fail in a way that is specific, detectable and repaired by
the same loop that a real continuity error would go through.

Determinism: every string comes from a ``random.Random`` seeded by
``engine.seed`` plus the identity of what is being generated. The same config
produces byte-identical output on any machine, which is what makes
``output/golden-tiny/`` a fixture you can diff.
"""

from __future__ import annotations

import hashlib
import random
import re
from typing import Any, Mapping, Sequence

from ..domain.models import Usage
from .base import Completion, EngineError, Request

__all__ = ["MockEngine"]

_CAST = (
    ("Mara Kassab", "salvage pilot", ("steady", "secretive")),
    ("Ilo Vega", "systems engineer", ("literal", "loyal")),
    ("Renn Adeyemi", "xenolinguist", ("curious", "sleepless")),
    ("Sabo Trell", "quartermaster", ("blunt", "superstitious")),
    ("Nieve Okonkwo", "flight surgeon", ("precise", "tired")),
    ("Dax Ferrow", "hull diver", ("reckless", "generous")),
    ("Yuki Barrow", "archivist", ("quiet", "stubborn")),
)

_FACTIONS = (
    ("the Tessellate Combine", "a salvage cartel that writes the law it enforces"),
    ("the Quiet Registry", "keepers of the wreck catalogue, and of what it omits"),
    ("the Outbound Union", "crews who sold their return tickets"),
    ("the Arbiters of Drift", "insurers with warships"),
)

_TECH = (
    ("mass-thread tether", "a monofilament line that holds a hull against spin"),
    ("echo core", "a memory lattice that replays what it was near"),
    ("cold-lamp rig", "a lamp that emits no heat, for volatile holds"),
    ("slow sleeve", "a pressure suit rated for months, not hours"),
    ("drift compass", "an inertial log that never forgets a burn"),
    ("hull chorus", "the resonance a ship makes when it is about to fail"),
)

_RULES = (
    "No faster-than-light travel. Every crossing is measured in months, and "
    "every message arrives late.",
    "Inertia is never cancelled. Thrust is felt in the spine, and a hard burn "
    "costs the crew something.",
    "An echo core can be read in place but never copied. To learn what it holds, "
    "you must go to it.",
    "Vacuum kills in under two minutes, and it is silent. Nothing outside the "
    "hull is ever heard.",
    "Salvage law grants title by contact, not by claim, which is why crews race "
    "and why they lie.",
    "The derelict answers questions it was asked before. It has no way to answer "
    "a new one.",
    "Power is the only real currency outbound; air is rationed against it.",
    "No crew may hold two registries at once, so a defection is permanent.",
)

_MYSTERIES = (
    "Why does the derelict's echo core hold the crew's own voices, recorded "
    "before they ever boarded?",
    "Who filed the wreck with the Quiet Registry eleven years before it was lost?",
    "What did Kassab agree to on her last contract, and who still holds that note?",
    "Where did the derelict's original crew go, given the pods are all still aboard?",
    "What is the hull chorus counting down to?",
)

_NOUNS = (
    "bulkhead", "tether", "airlock", "readout", "manifest", "corridor", "hatch",
    "ration tin", "handhold", "seam", "ladder", "cargo net", "vent", "console",
    "suit glove", "beacon", "stanchion", "pressure door", "strut", "panel",
)
_ADJ = (
    "cold", "unlit", "frost-rimed", "patient", "narrow", "scorched", "borrowed",
    "sealed", "humming", "wrong", "familiar", "unlabelled", "still", "shallow",
)
_VERBS = ("checked", "braced against", "counted", "distrusted", "listened to",
          "logged", "traced", "avoided", "reopened", "measured")

_SENTENCES = (
    "{a} {verb} the {adj} {noun} and said nothing about it.",
    "The {adj} {noun} had been {adj2} for longer than the manifest allowed.",
    "{a} put a glove on the {noun}; the {noun2} answered, one deck down.",
    "There was a {noun} where the drawings showed a {noun2}, and no one had logged the change.",
    "{a} read the {noun} twice, because the first answer had been the {adj} one.",
    "Somewhere aft, the {noun} shifted, and the sound arrived through the hull rather than the air.",
    "{b} wanted to go back. {a} wanted to know why the {noun} was {adj}.",
    "The {adj} {noun} was warm, which meant something aboard was still spending power.",
    "{a} marked the {noun} on the drift compass and did not explain the mark.",
    "“It knows the route,” {b} said. “It should not know the route.”",
    "The {noun} had been opened from the inside, and then closed the same way.",
    "{b} counted the {noun}s aloud, and stopped at a number that was too high.",
    "Nothing outside the hull made a sound, which was the only reassuring thing about it.",
    "{a} thought about the contract, and about how little of it had been in writing.",
    "The {adj} {noun} held. That was all anyone could ask of it.",
    "{b} logged the discrepancy, then logged that they had logged it.",
    "The lamps were {adj}, and the corridor went on further than the deck plan said.",
    "{a} had been aboard eleven minutes and already distrusted the {noun}.",
)

_TITLES = (
    "Contact by Law", "The Cold Lamp", "What the Core Kept", "Nothing Is Heard Outside",
    "Eleven Years Early", "A Number Too High", "The Long Burn", "Title by Contact",
    "The Quiet Registry", "Opened From Inside", "Late Messages", "The Hull Chorus",
    "Borrowed Air", "The Route It Knew", "Salvage Rights", "What Was Asked Before",
    "The Return Ticket", "Counting Aft", "One Deck Down", "The Last Contract",
    "Frost on the Seam", "No New Questions", "The Pods Are Aboard", "Permanent Defection",
    "Against the Spin", "The Second Answer", "Rationed", "A Mark Unexplained",
    "The Wreck Catalogue", "Months, Not Hours", "Spent Power", "The Drawings Lied",
    "Who Filed It", "The Voices Aboard",
)


def _drifted(surname: str) -> str:
    """A misspelling a human reader would skim past and a critic will not.

    One character, at the end, in the same character class - the shape of a
    real transcription error rather than a different name.
    """
    if len(surname) < 3:
        return surname + "e"
    swaps = {"b": "r", "a": "e", "r": "n", "l": "ll", "n": "m", "s": "z", "w": "v"}
    last = surname[-1].lower()
    return surname[:-1] + swaps.get(last, "n")


class MockEngine:
    """Deterministic text, shaped like the real thing."""

    name = "mock"

    def __init__(self, *, model: str, seed: int = 0, inject_drift: bool = True) -> None:
        self.model = model
        self.seed = int(seed)
        self.inject_drift = bool(inject_drift)
        self.calls = 0

    # -- the interface ---------------------------------------------------

    def complete(self, request: Request) -> Completion:
        task = dict(request.task or {})
        kind = request.kind
        builder = getattr(self, f"_build_{kind}", None)
        if builder is None:
            raise EngineError(
                f"mock engine has no generator for task kind {kind!r}; "
                f"add _build_{kind} or run --engine anthropic"
            )
        text = builder(task, self._rng(kind, task))
        self.calls += 1
        # Token counts are estimates on a 4-chars-per-token rule. They are
        # simulated; the pricing arithmetic they feed is not - which is why the
        # floor is applied *after* the division. A real call is never free, and
        # a short prompt reporting zero input tokens would understate spend in
        # exactly the way an unknown model priced at $0 would.
        return Completion(
            text=text,
            usage=Usage(
                model=self.model,
                input_tokens=max(1, (len(request.system) + len(request.prompt)) // 4),
                output_tokens=max(1, len(text) // 4),
            ),
            model=self.model,
        )

    def _seed_for(self, *parts: Any) -> int:
        """A stable seed from arbitrary parts.

        ``hash()`` is not usable here: Python randomises string hashing per
        process, so a run seeded that way would be deterministic *within* a run
        and different on the next one - which would quietly destroy the value
        of the committed golden fixture. SHA-256 is stable across processes,
        machines and Python versions.
        """
        material = "|".join(str(p) for p in (self.seed, *parts))
        digest = hashlib.sha256(material.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big")

    def _rng(self, kind: str, task: Mapping[str, Any]) -> random.Random:
        return random.Random(self._seed_for(
            kind, task.get("chapter", 0), task.get("iteration", 0), task.get("section", "")
        ))

    # -- cast and canon --------------------------------------------------

    def _cast(self, count: int) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
        return _CAST[:max(2, min(count, len(_CAST)))]

    def _build_world(self, task: Mapping[str, Any], rng: random.Random) -> str:
        premise = str(task.get("premise", "")).strip()
        tone = str(task.get("tone", "hard-scifi"))
        n_rules = int(task.get("rules", 4))
        n_tech = int(task.get("technology", 3))
        n_factions = int(task.get("factions", 2))

        lines = [
            "# World",
            "",
            f"The premise, as given: {premise}",
            "",
            "Distance is the antagonist. This is a "
            f"{tone} setting in which the nearest help is months away and the "
            "nearest law is whoever arrived first. Salvage is the only economy "
            "that reliably pays, and it pays for arrival, not for care.",
            "",
            "## Factions",
            "",
        ]
        for name, blurb in _FACTIONS[:n_factions]:
            lines.append(f"- **{name}** — {blurb}")
        lines += ["", "## Technology", ""]
        for name, blurb in _TECH[:n_tech]:
            lines.append(f"- **{name}** — {blurb}")
        # The heading must contain "rule": textops.parse_world_rules only reads
        # bullets under a rules heading, so the Science Auditor never audits
        # against a bullet that was describing a faction.
        lines += ["", "## Rules", ""]
        for rule in _RULES[:n_rules]:
            lines.append(f"- {rule}")
        lines += [
            "",
            "## Texture",
            "",
            "Ships are loud from the inside and silent from the outside. Crews "
            "speak in manifest numbers because the numbers are the only thing "
            "everyone aboard agrees on.",
        ]
        return "\n".join(lines)

    def _build_characters(self, task: Mapping[str, Any], rng: random.Random) -> str:
        cast = self._cast(int(task.get("characters", 4)))
        lines = [
            "# Characters",
            "",
            "Canonical spelling is fixed here. Every later stage is held "
            "against these names.",
            "",
        ]
        for name, role, traits in cast:
            lines.append(f"- **{name}** — {role}; {', '.join(traits)}")
        return "\n".join(lines)

    def _build_timeline(self, task: Mapping[str, Any], rng: random.Random) -> str:
        rows = int(task.get("rows", 6))
        events = [
            "The derelict is filed with the Quiet Registry.",
            "The derelict is reported lost, eleven years after it was filed.",
            "Kassab signs a contract whose terms are never written down.",
            "The crew departs outbound; the return leg is not funded.",
            "Contact. Title passes by touch, under salvage law.",
            "The echo core is read in place for the first time.",
            "The hull chorus begins, and is logged as a structural fault.",
            "Adeyemi identifies the recorded voices as the crew's own.",
            "The pods are found sealed, occupied by nobody.",
            "The Combine's arbiter ship changes course to intercept.",
            "Power falls below the ration line.",
            "The derelict answers a question nobody aboard has asked yet.",
        ]
        lines = ["# Timeline", "", "| When | Event |", "| --- | --- |"]
        for index, event in enumerate(events[:rows], start=1):
            lines.append(f"| T{index:+03d} | {event} |")
        return "\n".join(lines)

    def _build_mysteries(self, task: Mapping[str, Any], rng: random.Random) -> str:
        count = int(task.get("mysteries", 3))
        lines = ["# Mysteries", "",
                 "Each is a promise to the reader. The outline must pay them off.", ""]
        for mystery in _MYSTERIES[:count]:
            lines.append(f"- {mystery}")
        return "\n".join(lines)

    # -- outline ---------------------------------------------------------

    def _build_outline(self, task: Mapping[str, Any], rng: random.Random) -> str:
        chapters = int(task.get("chapters", 3))
        beats = int(task.get("beats", 3))
        promises = int(task.get("promises", 3))
        cast = self._cast(int(task.get("characters", 4)))
        povs = [name for name, _, _ in cast]

        lines = ["# Outline", "", "## Promises", ""]
        for mystery in _MYSTERIES[:promises]:
            lines.append(f"- {mystery}")
        lines += ["", "## Chapters", ""]
        for number in range(1, chapters + 1):
            title = _TITLES[(number - 1) % len(_TITLES)]
            pov = povs[(number - 1) % len(povs)]
            # A rising curve with a dip before the end: tension that only ever
            # rises reads as flat, because the reader stops registering it.
            span = max(1, chapters - 1)
            tension = 3 + round(6 * ((number - 1) / span))
            if chapters >= 4 and number == chapters - 1:
                tension = max(3, tension - 2)
            promise = _MYSTERIES[(number - 1) % promises]
            lines.append(f"### Chapter {number} — {title}")
            lines.append(f"- **POV:** {pov}")
            lines.append(f"- **Tension:** {min(10, tension)}/10")
            lines.append(f"- **Promise advanced:** {promise}")
            lines.append("- **Beats:**")
            pool = list(_SENTENCES)
            rng_local = random.Random(self._seed_for("beats", number))
            rng_local.shuffle(pool)
            for beat_index in range(beats):
                template = pool[beat_index % len(pool)]
                lines.append("  - " + self._fill(template, povs, rng_local).rstrip("."))
            lines.append("")
        return "\n".join(lines)

    # -- prose -----------------------------------------------------------

    def _fill(self, template: str, names: Sequence[str], rng: random.Random) -> str:
        a = rng.choice(names)
        b = rng.choice([n for n in names if n != a] or list(names))
        return template.format(
            a=a, b=b,
            verb=rng.choice(_VERBS),
            adj=rng.choice(_ADJ), adj2=rng.choice(_ADJ),
            noun=rng.choice(_NOUNS), noun2=rng.choice(_NOUNS),
        )

    def _build_chapter(self, task: Mapping[str, Any], rng: random.Random) -> str:
        number = int(task.get("chapter", 1))
        iteration = int(task.get("iteration", 1))
        target = int(task.get("target_words", 420))
        title = str(task.get("title") or _TITLES[(number - 1) % len(_TITLES)])
        names = [str(n) for n in task.get("names", ())] or [c[0] for c in self._cast(4)]
        sentences_per_para = int(task.get("sentences_per_paragraph", 3))

        body: list[str] = []
        words = 0
        paragraph: list[str] = []
        guard = 0
        while words < target and guard < 400:
            guard += 1
            sentence = self._fill(rng.choice(_SENTENCES), names, rng)
            paragraph.append(sentence)
            words += len(sentence.split())
            if len(paragraph) >= sentences_per_para:
                body.append(" ".join(paragraph))
                paragraph = []
        if paragraph:
            body.append(" ".join(paragraph))

        text = f"# Chapter {number} — {title}\n\n" + "\n\n".join(body) + "\n"

        # The deliberate failure. Even chapters, first draft only: one canonical
        # surname is misspelled. The Continuity Critic quotes it, the gate
        # rejects, and iteration 2 (which skips this branch) comes back clean.
        if self.inject_drift and iteration == 1 and number % 2 == 0:
            text = self._drift_one_surname(text, names)
        return text

    def _drift_one_surname(self, text: str, names: Sequence[str]) -> str:
        for full_name in names:
            surname = full_name.split()[-1]
            if len(surname) < 3:
                continue
            pattern = re.compile(r"\b" + re.escape(surname) + r"\b")
            if pattern.search(text):
                return pattern.sub(_drifted(surname), text, count=1)
        return text

    def _build_summary(self, task: Mapping[str, Any], rng: random.Random) -> str:
        """Extractive: the first sentence of the first and last paragraphs.

        Extractive on purpose. The rolling summary is the one sanctioned
        channel for prior-chapter material, and an extractive summary is honest
        about sharing wording with the chapter it came from - which is exactly
        why :func:`novaforge.context.assert_no_prior_prose` is told to skip it.
        """
        chapter_text = str(task.get("text", ""))
        blocks = [b.strip() for b in re.split(r"\n\s*\n", chapter_text)
                  if b.strip() and not b.strip().startswith("#")]
        if not blocks:
            return ""
        picks = [blocks[0]] if len(blocks) == 1 else [blocks[0], blocks[-1]]
        out = []
        for block in picks:
            first = re.split(r"(?<=[.!?])\s+", block.strip())[0]
            out.append(first.strip())
        return " ".join(out)

    def _build_style(self, task: Mapping[str, Any], rng: random.Random) -> str:
        """One voice across chapters written in isolation.

        Whitespace and punctuation only. A style pass that rewrote sentences
        would invalidate the critique the chapter just passed, so this one is
        deliberately unable to change what the gate measured.
        """
        text = str(task.get("text", ""))
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" +\n", "\n", text)
        text = text.replace(" - ", " — ").replace("--", "—")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.rstrip() + "\n"

    def _build_synopsis(self, task: Mapping[str, Any], rng: random.Random) -> str:
        min_words = int(task.get("min_words", 150))
        comparables = int(task.get("comparables", 2))
        premise = str(task.get("premise", ""))
        names = [str(n) for n in task.get("names", ())] or ["Mara Kassab"]
        parts = [
            f"{premise.rstrip('.')}.",
            f"{names[0]} takes the contract because the alternative is the return "
            "leg nobody funded, and salvage law grants title by contact rather "
            "than by claim — which means the crew that touches the hull first "
            "owns whatever is inside it, and the crews that arrive second have "
            "every reason to dispute the record.",
            "What is inside it is a memory. The derelict's echo core holds "
            "voices the crew recognise as their own, recorded before any of "
            "them signed on, and the core cannot be copied — it can only be "
            "read in place, which keeps everyone aboard long past the point "
            "where leaving was still an option.",
            "The distances are honest ones. Nothing travels faster than light, "
            "every message arrives late, and a hard burn costs the crew "
            "something they do not get back. The pressure is not an enemy ship; "
            "it is the ration line, the arbiter's changed course, and the "
            "question of who filed this wreck eleven years before it was lost.",
        ]
        while len(" ".join(parts).split()) < min_words:
            parts.append(
                "Outbound, the only real currency is power, and air is rationed "
                "against it.")
        if comparables:
            comps = ["*Solaris*", "*The Left Hand of Darkness*", "*Blindsight*"]
            parts.append("Comparable to " + " and ".join(comps[:comparables]) + ".")
        return " ".join(parts)
