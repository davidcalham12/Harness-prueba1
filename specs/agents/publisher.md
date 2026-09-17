# Publisher — agent spec

- **name:** `publisher`
- **model:** `sonnet`
- **writes_bible:** false
- **stage:** FLOW-6
- **subagent:** `.claude/agents/publisher.md`

Synopsis from the model; Markdown and PDF from code.

## Requirements

### AGT-PB-1 — Writes the synopsis; code assembles the manuscript

A model asked to assemble the book paraphrases a sentence somewhere in the
middle, after the gate approved it.

### AGT-PB-2 — A configured format with no exporter is reported by name

A run that quietly writes one file when the config asked for two is a run
that lies in its summary.

## Authority

`writes_bible` above is the spec's statement and `specs/flow.yaml` is the other
half of it. On this branch it is held by the subagent's tool list: only the two
Bible writers carry the Write tool, and every other agent returns text that the
orchestrator writes to disk. An agent cannot grant itself Bible access by editing
its own front matter, because what it would have to edit is that tool list, and
the tool list is the thing a reviewer reads (SEC-4).
