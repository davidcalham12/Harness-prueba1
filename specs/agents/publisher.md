# Publisher — agent spec

- **role:** `publisher`
- **model:** `claude-sonnet-5`
- **writes_bible:** false
- **stage:** FLOW-6
- **skill:** `.claude/skills/publisher/SKILL.md`

Synopsis from the model; Markdown and PDF from code.

## Requirements

### AGT-PB-1 — Writes the synopsis; code assembles the manuscript

A model asked to assemble the book paraphrases a sentence somewhere in the
middle, after the gate approved it.

### AGT-PB-2 — A configured format with no exporter is reported by name

A run that quietly writes one file when the config asked for two is a run
that lies in its summary.

## Authority

`writes_bible` above is checked against `specs/flow.yaml` and against
`novaforge.security.prompting.BIBLE_WRITERS` at load time. A skill file cannot
grant itself Bible access by editing its own front matter (SEC-4.3).
