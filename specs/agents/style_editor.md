# Style Editor — agent spec

- **role:** `style_editor`
- **model:** `claude-sonnet-5`
- **writes_bible:** false
- **stage:** FLOW-5
- **skill:** `.claude/skills/style_editor/SKILL.md`

One voice across chapters written independently of each other.

## Requirements

### AGT-SE-1 — Does not change the word count of a chapter

The chapters it edits have already been approved. A style pass that rewrote
prose would mean the published text is not the text the critics judged.

### AGT-SE-2 — Writes chapters/chNN.final.md without destroying the approved draft

The draft and the final are both kept, so the effect of this stage is a diff
rather than an assertion.

## Authority

`writes_bible` above is checked against `specs/flow.yaml` and against
`novaforge.security.prompting.BIBLE_WRITERS` at load time. A skill file cannot
grant itself Bible access by editing its own front matter (SEC-4.3).
