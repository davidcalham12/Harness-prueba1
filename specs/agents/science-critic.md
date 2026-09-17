# Science Critic — agent spec

- **name:** `science-critic`
- **model:** `sonnet`
- **writes_bible:** false
- **stage:** FLOW-4
- **subagent:** `.claude/agents/science-critic.md`

> **On the shipping path, and that is the trade this branch made.** The Python
> build scored the rules in code so a run would reproduce byte for byte. Here a
> model scores them, which is what the prompt was always written for — and it
> means the gate no longer reproduces. The same draft can clear it one run and
> not the next. Say so when reporting a run.

Holds a draft against the rules in bible/world.md.

## Requirements

### AGT-SC-1 — Only enforces rules the world actually declared

A setting that permits FTL is not wrong for using it. A critic enforcing its
own physics would be auditing a book nobody wrote.

### AGT-SC-2 — Quotes the whole offending sentence, not the phrase

The writer has to find it in the draft to fix it.

## Authority

`writes_bible` above is the spec's statement and `specs/flow.yaml` is the other
half of it. On this branch it is held by the subagent's tool list: only the two
Bible writers carry the Write tool, and every other agent returns text that the
orchestrator writes to disk. An agent cannot grant itself Bible access by editing
its own front matter, because what it would have to edit is that tool list, and
the tool list is the thing a reviewer reads (SEC-4).
