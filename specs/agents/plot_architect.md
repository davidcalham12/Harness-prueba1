# Plot Architect — agent spec

- **role:** `plot_architect`
- **model:** `claude-opus-5`
- **writes_bible:** false
- **stage:** FLOW-3
- **skill:** `.claude/skills/plot_architect/SKILL.md`

Acts, per-chapter tension curve and reader promises.

## Requirements

### AGT-PA-1 — Produces exactly `novel.chapters` entries, numbered from 1 with no gaps

A missing entry is a chapter with no plot context at all, since the outline
entry is the writer's entire view of the story.

### AGT-PA-2 — Every entry carries POV, tension and beats

The beats are what distinguish an outline from a summary. An entry with no
beats leaves its chapter to be written from the Bible and a title.

## Authority

`writes_bible` above is checked against `specs/flow.yaml` and against
`novaforge.security.prompting.BIBLE_WRITERS` at load time. A skill file cannot
grant itself Bible access by editing its own front matter (SEC-4.3).
