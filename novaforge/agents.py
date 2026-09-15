"""Agents, defined outside this package.

``specs/flow.yaml`` says which agent runs at each stage. This module says what
an agent *is*: a role, a model, whether it may write the Story Bible, and the
system prompt it is given - all read from ``.claude/skills/<name>/SKILL.md``
rather than written in Python.

That is the third leg of the claim in :mod:`novaforge`'s docstring, and the
reason it matters is narrow and practical: a prompt is the part of an agent
most likely to need changing, and the part least likely to need a code review.
Keeping it in a Markdown file means editing it is editing a document.

**Authority is not read from the skill.** ``writes_bible`` in the front matter
is cross-checked against ``specs/flow.yaml`` and against
:data:`novaforge.security.prompting.BIBLE_WRITERS`, and a disagreement refuses
to load. A file that could grant itself Bible access by editing its own front
matter would make SEC-4.3 a suggestion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

from .spec.miniyaml import YamlError, safe_load

__all__ = ["Agent", "AgentError", "AgentRegistry", "load_agents"]

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)
_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.M)
_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")

PROMPT_SECTION = "System prompt"


class AgentError(ValueError):
    """A skill file is missing, malformed, or contradicts the flow spec."""


@dataclass(frozen=True)
class Agent:
    """One agent, as its ``SKILL.md`` defines it."""

    name: str
    role: str
    model: str | None
    writes_bible: bool
    prompt: str
    spec_path: str
    source: str
    on_shipping_path: bool = True

    @property
    def placeholders(self) -> frozenset[str]:
        """The ``{name}`` slots the prompt expects the caller to fill."""
        return frozenset(_PLACEHOLDER.findall(self.prompt))

    def system(self, **values: Any) -> str:
        """The system prompt with its placeholders filled.

        A placeholder with no value raises rather than being left in the
        prompt: ``"a {tone} novel"`` reaching a model verbatim is a prompt bug
        that reads as a strange instruction, and it would be invisible in the
        output.
        """
        missing = self.placeholders - set(values)
        if missing:
            raise AgentError(
                f"{self.source}: prompt needs {sorted(missing)}, which the caller "
                f"did not supply"
            )
        out = self.prompt
        for key, value in values.items():
            out = out.replace("{" + key + "}", str(value))
        return out


def _split_front_matter(text: str, source: str) -> tuple[Mapping[str, Any], str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        raise AgentError(f"{source}: no YAML front matter (a '---' delimited block)")
    try:
        data = safe_load(match.group(1))
    except YamlError as exc:
        raise AgentError(f"{source}: front matter is not readable: {exc}") from exc
    if not isinstance(data, Mapping):
        raise AgentError(f"{source}: front matter must be a mapping")
    return data, match.group(2)


def _section(body: str, title: str, source: str) -> str:
    """The text under ``## <title>``, up to the next ``##``."""
    positions = [(m.group(1), m.start(), m.end()) for m in _SECTION.finditer(body)]
    for index, (name, _start, end) in enumerate(positions):
        if name.strip().lower() != title.lower():
            continue
        stop = positions[index + 1][1] if index + 1 < len(positions) else len(body)
        return body[end:stop].strip()
    raise AgentError(f"{source}: no '## {title}' section")


def _parse_skill(path: Path) -> Agent:
    source = str(path).replace("\\", "/")
    front, body = _split_front_matter(path.read_text(encoding="utf-8"), source)

    for required in ("name", "role", "spec"):
        if not front.get(required):
            raise AgentError(f"{source}: front matter is missing {required!r}")

    name = str(front["name"])
    if name != path.parent.name:
        raise AgentError(
            f"{source}: front matter says name {name!r} but the directory is "
            f"{path.parent.name!r}; the directory is the address"
        )

    prompt = _section(body, PROMPT_SECTION, source)
    if not prompt:
        raise AgentError(f"{source}: the '## {PROMPT_SECTION}' section is empty")

    return Agent(
        name=name,
        role=str(front["role"]),
        model=str(front["model"]) if front.get("model") else None,
        writes_bible=bool(front.get("writes_bible", False)),
        prompt=prompt,
        spec_path=str(front["spec"]),
        source=source,
        # A skill whose prompt this build never sends. Declared rather than
        # discovered, so an unused prompt is a stated fact instead of a
        # surprise - the same reason SEC-5 says so about its XML escapers.
        on_shipping_path=bool(front.get("shipping", True)),
    )


class AgentRegistry:
    """Every agent the project defines, keyed by role."""

    def __init__(self, agents: Mapping[str, Agent], *, root: Path) -> None:
        self._agents = dict(agents)
        self.root = root

    def __len__(self) -> int:
        return len(self._agents)

    def __iter__(self) -> Iterator[Agent]:
        return iter(sorted(self._agents.values(), key=lambda a: a.name))

    def __contains__(self, role: object) -> bool:
        return role in self._agents

    def get(self, role: str) -> Agent:
        if role not in self._agents:
            raise AgentError(
                f"no skill defines the agent {role!r}; have "
                f"{sorted(self._agents)}. Add "
                f".claude/skills/{role}/SKILL.md"
            )
        return self._agents[role]

    @property
    def shipping(self) -> tuple[Agent, ...]:
        return tuple(a for a in self if a.on_shipping_path)

    def check_against_flow(self, spec) -> None:
        """Refuse to run if a skill and the flow spec disagree (SEC-4.3).

        Checked in both directions. A stage naming an agent with no skill has
        no prompt to send; a skill claiming Bible authority the spec never
        granted is a file trying to promote itself.
        """
        from .security.prompting import BIBLE_WRITERS

        for stage in spec.stages:
            agent = self.get(stage.agent)
            if agent.writes_bible != stage.writes_bible:
                raise AgentError(
                    f"{agent.source}: front matter says writes_bible="
                    f"{agent.writes_bible}, but {stage.id} in {spec.source} says "
                    f"{stage.writes_bible}. Authority comes from the spec."
                )

        claiming = {a.role for a in self if a.writes_bible}
        if claiming != BIBLE_WRITERS:
            raise AgentError(
                f"skills claiming Bible authority are {sorted(claiming)}, but "
                f"security.prompting says {sorted(BIBLE_WRITERS)} (SEC-4.3)"
            )


def load_agents(root: str | Path | None = None) -> AgentRegistry:
    """Read every ``.claude/skills/*/SKILL.md``."""
    from .config import package_root

    base = Path(root) if root is not None else package_root()
    skills_dir = base / ".claude" / "skills"
    if not skills_dir.is_dir():
        raise AgentError(
            f"no skills directory at {skills_dir}. Agents are data this program "
            f"reads; there are no built-in prompts to fall back to."
        )

    agents: dict[str, Agent] = {}
    for path in sorted(skills_dir.glob("*/SKILL.md")):
        agent = _parse_skill(path)
        if agent.role in agents:
            raise AgentError(
                f"{agent.source}: role {agent.role!r} is already defined by "
                f"{agents[agent.role].source}"
            )
        agents[agent.role] = agent

    if not agents:
        raise AgentError(f"{skills_dir} contains no SKILL.md files")
    return AgentRegistry(agents, root=base)
