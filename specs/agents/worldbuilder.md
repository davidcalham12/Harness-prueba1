# Worldbuilder — agent spec

- **name:** `worldbuilder`
- **model:** `opus`
- **writes_bible:** true
- **stage:** FLOW-1
- **subagent:** `.claude/agents/worldbuilder.md`

Turn the premise into the physical and political rules of the world.

## Requirements

### AGT-WB-1 — Writes bible/world.md and nothing else

The stage writes exactly one Bible section. Writing a second would give one
agent authority the spec granted for one file.

### AGT-WB-2 — Declares at least `bible.world_rules.min` rules under a `## Rules` heading

The science critic is given the bullets from under a rules heading and nowhere
else, so a constraint written anywhere else is never enforced at all. The count
comes from the config, not from the prompt.

## Authority

`writes_bible` above is the spec's statement and `specs/flow.yaml` is the other
half of it. On this branch it is held by the subagent's tool list: only the two
Bible writers carry the Write tool, and every other agent returns text that the
orchestrator writes to disk. An agent cannot grant itself Bible access by editing
its own front matter, because what it would have to edit is that tool list, and
the tool list is the thing a reviewer reads (SEC-4).
