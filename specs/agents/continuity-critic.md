# Continuity Critic — agent spec

- **name:** `continuity-critic`
- **model:** `sonnet`
- **writes_bible:** false
- **stage:** FLOW-4
- **subagent:** `.claude/agents/continuity-critic.md`

> **On the shipping path, and that is the trade this branch made.** The Python
> build scored continuity in code so a run would reproduce byte for byte. Here a
> model scores it, which is what the prompt was always written for — and it means
> the gate no longer reproduces. The same draft can clear it one run and not the
> next. Say so when reporting a run; do not describe a passed gate as a property
> of the text.

Holds a draft against bible/characters.md.

## Requirements

### AGT-CC-1 — Reports a name one edit from a canonical one, quoting it

The commonest real failure, because the writer never saw the previous
chapter. The quote is what the rewrite acts on.

### AGT-CC-2 — Judges against the Story Bible, never against earlier chapters

Comparing chapters to each other would reintroduce exactly the dependency
the context policy removes, and get slower with every chapter.

## Authority

`writes_bible` above is the spec's statement and `specs/flow.yaml` is the other
half of it. On this branch it is held by the subagent's tool list: only the two
Bible writers carry the Write tool, and every other agent returns text that the
orchestrator writes to disk. An agent cannot grant itself Bible access by editing
its own front matter, because what it would have to edit is that tool list, and
the tool list is the thing a reviewer reads (SEC-4).
