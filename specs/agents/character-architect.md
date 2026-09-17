# Character Architect — agent spec

- **name:** `character-architect`
- **model:** `opus`
- **writes_bible:** true
- **stage:** FLOW-2
- **subagent:** `.claude/agents/character-architect.md`

Cast, timeline and mysteries. Fixes canonical spelling for the whole novel.

## Requirements

### AGT-CA-1 — Writes characters, timeline and mysteries, in that order

The timeline and the mysteries both name characters, so the cast must be
canonical before either is written.

### AGT-CA-2 — Cast entries parse as `- **Full Name** — role; traits`

The orchestrator reads this shape to lift the canonical names. A cast it cannot read
is a cast the Continuity Critic cannot check against, and the run would
silently stop enforcing names.

## Authority

`writes_bible` above is the spec's statement and `specs/flow.yaml` is the other
half of it. On this branch it is held by the subagent's tool list: only the two
Bible writers carry the Write tool, and every other agent returns text that the
orchestrator writes to disk. An agent cannot grant itself Bible access by editing
its own front matter, because what it would have to edit is that tool list, and
the tool list is the thing a reviewer reads (SEC-4).
