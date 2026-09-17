# Plot Architect — agent spec

- **name:** `plot-architect`
- **model:** `opus`
- **writes_bible:** false
- **stage:** FLOW-3
- **subagent:** `.claude/agents/plot-architect.md`

Acts, per-chapter tension curve and reader promises.

## Requirements

### AGT-PA-1 — Produces exactly `novel.chapters` entries, numbered from 1 with no gaps

A missing entry is a chapter with no plot context at all, since the outline
entry is the writer's entire view of the story.

### AGT-PA-2 — Every entry carries POV, tension and beats

The beats are what distinguish an outline from a summary. An entry with no
beats leaves its chapter to be written from the Bible and a title.

## Authority

`writes_bible` above is the spec's statement and `specs/flow.yaml` is the other
half of it. On this branch it is held by the subagent's tool list: only the two
Bible writers carry the Write tool, and every other agent returns text that the
orchestrator writes to disk. An agent cannot grant itself Bible access by editing
its own front matter, because what it would have to edit is that tool list, and
the tool list is the thing a reviewer reads (SEC-4).
