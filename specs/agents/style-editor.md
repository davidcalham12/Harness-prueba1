# Style Editor — agent spec

- **name:** `style-editor`
- **model:** `sonnet`
- **writes_bible:** false
- **stage:** FLOW-5
- **subagent:** `.claude/agents/style-editor.md`

One voice across chapters written independently of each other.

## Requirements

### AGT-SE-1 — Does not change the word count of a chapter

The chapters it edits have already been approved. A style pass that rewrote
prose would mean the published text is not the text the critics judged.

### AGT-SE-2 — Writes chapters/chNN.final.md without destroying the approved draft

The draft and the final are both kept, so the effect of this stage is a diff
rather than an assertion.

## Authority

`writes_bible` above is the spec's statement and `specs/flow.yaml` is the other
half of it. On this branch it is held by the subagent's tool list: only the two
Bible writers carry the Write tool, and every other agent returns text that the
orchestrator writes to disk. An agent cannot grant itself Bible access by editing
its own front matter, because what it would have to edit is that tool list, and
the tool list is the thing a reviewer reads (SEC-4).
