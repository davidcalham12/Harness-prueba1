# Character Architect — agent spec

- **role:** `character_architect`
- **model:** `claude-opus-5`
- **writes_bible:** true
- **stage:** FLOW-2
- **skill:** `.claude/skills/character_architect/SKILL.md`

Cast, timeline and mysteries. Fixes canonical spelling for the whole novel.

## Requirements

### AGT-CA-1 — Writes characters, timeline and mysteries, in that order

The timeline and the mysteries both name characters, so the cast must be
canonical before either is written.

### AGT-CA-2 — Cast entries parse as `- **Full Name** — role; traits`

`textops.parse_characters` reads this shape. A cast the parser cannot read
is a cast the Continuity Critic cannot check against, and the run would
silently stop enforcing names.

## Authority

`writes_bible` above is checked against `specs/flow.yaml` and against
`novaforge.security.prompting.BIBLE_WRITERS` at load time. A skill file cannot
grant itself Bible access by editing its own front matter (SEC-4.3).
