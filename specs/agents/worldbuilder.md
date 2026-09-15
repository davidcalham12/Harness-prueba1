# Worldbuilder — agent spec

- **role:** `worldbuilder`
- **model:** `claude-opus-5`
- **writes_bible:** true
- **stage:** FLOW-1
- **skill:** `.claude/skills/worldbuilder/SKILL.md`

Turn the premise into the physical and political rules of the world.

## Requirements

### AGT-WB-1 — Writes bible/world.md and nothing else

The stage writes exactly one Bible section. Writing a second would give one
agent authority the spec granted for one file.

### AGT-WB-2 — Declares at least `bible.world_rules.min` rules under a `## Rules` heading

`textops.parse_world_rules` reads bullets from under a rules heading and
nowhere else, so a constraint written elsewhere is never enforced by the
Science Auditor. The count comes from the config, not from the prompt.

## Authority

`writes_bible` above is checked against `specs/flow.yaml` and against
`novaforge.security.prompting.BIBLE_WRITERS` at load time. A skill file cannot
grant itself Bible access by editing its own front matter (SEC-4.3).
