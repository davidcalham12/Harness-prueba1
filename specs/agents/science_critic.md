# Science Critic — agent spec

- **role:** `science_critic`
- **model:** `claude-sonnet-5`
- **writes_bible:** false
- **stage:** FLOW-4
- **skill:** `.claude/skills/science_critic/SKILL.md`

> **Not on the shipping path in this build.** Scored in code by
> `novaforge/critics/science.py` so that a mock run is
> reproducible. The skill's prompt is what a model-backed critic receives once
> `--engine anthropic` exists. `tools/check_specs.py` reports this rather than
> hiding it.

Holds a draft against the rules in bible/world.md.

## Requirements

### AGT-SC-1 — Only enforces rules the world actually declared

A setting that permits FTL is not wrong for using it. A critic enforcing its
own physics would be auditing a book nobody wrote.

### AGT-SC-2 — Quotes the whole offending sentence, not the phrase

The writer has to find it in the draft to fix it.

## Authority

`writes_bible` above is checked against `specs/flow.yaml` and against
`novaforge.security.prompting.BIBLE_WRITERS` at load time. A skill file cannot
grant itself Bible access by editing its own front matter (SEC-4.3).
