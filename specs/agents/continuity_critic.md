# Continuity Critic — agent spec

- **role:** `continuity_critic`
- **model:** `claude-sonnet-5`
- **writes_bible:** false
- **stage:** FLOW-4
- **skill:** `.claude/skills/continuity_critic/SKILL.md`

> **Not on the shipping path in this build.** Scored in code by
> `novaforge/critics/continuity.py` so that a mock run is
> reproducible. The skill's prompt is what a model-backed critic receives once
> `--engine anthropic` exists. `tools/check_specs.py` reports this rather than
> hiding it.

Holds a draft against bible/characters.md.

## Requirements

### AGT-CC-1 — Reports a name one edit from a canonical one, quoting it

The commonest real failure, because the writer never saw the previous
chapter. The quote is what the rewrite acts on.

### AGT-CC-2 — Judges against the Story Bible, never against earlier chapters

Comparing chapters to each other would reintroduce exactly the dependency
the context policy removes, and get slower with every chapter.

## Authority

`writes_bible` above is checked against `specs/flow.yaml` and against
`novaforge.security.prompting.BIBLE_WRITERS` at load time. A skill file cannot
grant itself Bible access by editing its own front matter (SEC-4.3).
