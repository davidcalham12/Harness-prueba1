# Chapter Writer — agent spec

- **role:** `chapter_writer`
- **model:** `claude-opus-5`
- **writes_bible:** false
- **stage:** FLOW-4
- **skill:** `.claude/skills/chapter_writer/SKILL.md`

Draft each chapter, then hold it against the critics until it clears the gate.

## Requirements

### AGT-CW-1 — Never receives prior chapter prose

Enforced at runtime by `context.assert_no_prior_prose`, which re-reads the
assembled prompt before it is sent. This is the architectural claim of the
project, so it is code and not a request in a prompt.

### AGT-CW-2 — Receives the previous draft's findings on a rewrite, each quoting its text

A rewrite told only that it failed is a rewrite with nothing to act on.

## Authority

`writes_bible` above is checked against `specs/flow.yaml` and against
`novaforge.security.prompting.BIBLE_WRITERS` at load time. A skill file cannot
grant itself Bible access by editing its own front matter (SEC-4.3).
