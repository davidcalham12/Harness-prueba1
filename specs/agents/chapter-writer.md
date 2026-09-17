# Chapter Writer — agent spec

- **name:** `chapter-writer`
- **model:** `opus`
- **writes_bible:** false
- **stage:** FLOW-4
- **subagent:** `.claude/agents/chapter-writer.md`

Draft each chapter, then hold it against the critics until it clears the gate.

## Requirements

### AGT-CW-1 — Never receives prior chapter prose

The architectural claim of the project, so it is held by a capability and not by
a request in a prompt. The subagent runs in its own context window and its tool
list is `Glob` alone — which returns paths and cannot return the contents of a
file, so `chapters/ch01.md` is unreachable even deliberately. The orchestrator's
half is to assemble the prompt from the Bible, one outline entry and a capped
summary. Adding `Read` or `Bash` to that agent revokes the guarantee.

### AGT-CW-2 — Receives the previous draft's findings on a rewrite, each quoting its text

A rewrite told only that it failed is a rewrite with nothing to act on.

## Authority

`writes_bible` above is the spec's statement and `specs/flow.yaml` is the other
half of it. On this branch it is held by the subagent's tool list: only the two
Bible writers carry the Write tool, and every other agent returns text that the
orchestrator writes to disk. An agent cannot grant itself Bible access by editing
its own front matter, because what it would have to edit is that tool list, and
the tool list is the thing a reviewer reads (SEC-4).
