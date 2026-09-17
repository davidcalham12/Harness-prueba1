# NovaForge — Claude Code as the orchestrator

A spec-driven multi-agent harness that writes science-fiction novels, with
Claude Code as the orchestrator and eight subagents doing the work.

Eight agents, a quality gate that rejects its own drafts, and a context policy
that keeps the prompt the same size at chapter 34 as at chapter 1 — **held here
by a capability rather than by an assertion.**

```
> /novaforge
  premise: A deep-space salvage crew finds a derelict that remembers them
  profile: tiny
```

There is nothing to install. It runs inside Claude Code and nowhere else.

> **This is one of two branches, and they are not interchangeable.**
>
> `main` is the Python implementation: 810 tests, a byte-for-byte reproducible
> fixture, a hash-chained audit log, pre-call budget ceilings, six security
> layers and a Langfuse integration. It runs headless, so it runs in CI. Its one
> weakness is that the shipping engine is a mock that ignores your premise, so
> the thing it claims to do was never demonstrated.
>
> **This branch** deletes all of that and keeps the spec, the config and the
> prompts. In exchange the context policy becomes structural, and a real model
> writes a real novel from your actual premise on the first run.
>
> `specs/changes/CHG-003-claude-as-orchestrator.md` is the full account of the
> trade, including everything it cost.

## The idea

A novel does not fit in a context window, and the usual answer — feed the model
more of what it already wrote — gets slower and vaguer with every chapter.

NovaForge takes the opposite approach. **The chapter writer never sees a previous
chapter's prose.** It gets the Story Bible, its own outline entry, and a rolling
summary capped at a configured word count. Nothing else. The prompt for chapter
34 is the same size as the prompt for chapter 1.

That only works if two things hold:

- **Continuity comes from the Bible, not from memory.** The Story Bible is the
  single shared state, and the critics hold every draft against it.
- **The policy cannot be circumvented.** This is where the two branches differ,
  and it is the reason this one exists.

### The one line worth reading in this repository

```yaml
# .claude/agents/chapter-writer.md
tools: Glob
```

`Glob` returns file paths. It cannot return the contents of a file. The
`chapter-writer` subagent runs in its own context window, so no earlier chapter
is behind it, and with `Glob` alone it cannot go and fetch one either —
`chapters/ch01.md` is unreachable to it even deliberately.

On `main` the same policy is a runtime assertion that re-reads the assembled
prompt and raises if ten consecutive words from an earlier chapter leaked in.
That is a good check. It is still a check: something that runs after the prompt
is built, and that can be removed without the architecture noticing.

Here it is arithmetic about what the agent can do. That is a different kind of
claim, and it is the whole argument for this branch.

## Three files own the pipeline. None of them is code.

| File | Owns | Change it to… |
| --- | --- | --- |
| `specs/flow.yaml` | **Structure** — which stages exist, their order, which agent runs each, which may write the Bible | reorder or add a stage |
| `config/novel.config.json` | **Numbers** — lengths, gate threshold, draft allowance | write a longer book, or a stricter one |
| `.claude/agents/*.md` | **Prompts** — what each agent is told, and what it is allowed to do | change how an agent writes |

`.claude/skills/novaforge/SKILL.md` is the procedure that reads all three. It
contains no stage list, no threshold and no prompt of its own.

**Nothing enforces that.** On `main`, `tools/check_specs.py` failed if a stage
named an agent with no skill, if a skill contradicted its spec, or if a declared
requirement had no test citing it. There is no equivalent here — drift between
`specs/flow.yaml` and `.claude/agents/` will happen silently, and a reader is the
only thing that catches it.

## The agents

Six run as stages, two are critics.

| Agent | Stage | Tools | Writes the Bible |
| --- | --- | --- | --- |
| `worldbuilder` | FLOW-1 | `Write` | yes |
| `character-architect` | FLOW-2 | `Write` | yes |
| `plot-architect` | FLOW-3 | `Glob` | no |
| `chapter-writer` | FLOW-4 | `Glob` | no |
| `style-editor` | FLOW-5 | `Glob` | no |
| `publisher` | FLOW-6 | `Glob` | no |
| `continuity-critic` | FLOW-4 gate | `Glob` | no |
| `science-critic` | FLOW-4 gate | `Glob` | no |

**The Tools column is the authority model.** Only the two Bible writers can write
a file at all; the other six return text that the orchestrator writes. An agent
told to write canon cannot comply, whatever a prompt persuades it of. On `main`
this was a code check keyed on the invoked role — equally sound, and one more
thing that had to be kept correct.

## The gate

Four critics on every chapter draft, aggregated with `min` — **a chapter is only
as good as its worst critic.** Below `quality_gate.threshold` the findings go back
to the writer, quoted verbatim, and it redrafts. After
`quality_gate.max_revisions` rewrites the best draft is accepted with a warning.

| Critic | Who runs it | Reproducible |
| --- | --- | --- |
| `length` | the orchestrator, `wc -w` | yes |
| `chatter` | the orchestrator, a heading scan | yes |
| `continuity` | `continuity-critic` subagent | **no** |
| `science` | `science-critic` subagent | **no** |

The two model critics are the honest cost of this branch. The same draft can
score 8 one run and 7 the next, so **"it passed the gate" is a statement about
one run, not a property of the text.** On `main` all four were deterministic,
which is what made a committed fixture possible.

Every iteration is kept in `critiques/chNN.<critic>.json` — the failing score and
its quoted findings, not just the accepted one. That file is the evidence the
gate did something, and it is the first thing to open when someone asks whether
this pipeline is real.

## Try it

In Claude Code, in this directory:

```
/novaforge
```

Give it a premise and a profile. `tiny` is three chapters and the fastest way to
see the whole pipeline; `full` is thirty-four chapters through a four-critic
gate, so read the call count in the plan before starting one.

It writes `output/<slug>/`:

```
bible/         world.md, characters.md, timeline.md, mysteries.md
outline.md     acts, per-chapter tension curve, reader promises
chapters/      chNN.md, chNN.summary.md, chNN.final.md
critiques/     chNN.<critic>.json — every iteration, not just the last
synopsis.md
dist/book.md
logs/          agents.jsonl, one row per subagent call
state.json     resumable
config.snapshot.json
```

No PDF. That was `novaforge/export/pdf.py`, which wrote A5 pages against real
Helvetica metrics with no dependency, and it went with the package.

## What this branch does not give you

Stated here rather than buried, because five of these were real properties that
`main` still has.

- **No automated verification of anything.** There is no test suite.
  `specs/acceptance.md` marks each criterion as held by construction, checked by
  the orchestrator, or unverified.
- **No reproducibility.** Two runs of the same premise differ. There is no
  committed fixture to diff.
- **No tamper-evident audit.** `logs/agents.jsonl` is a flat file. Nothing
  detects a row edited, removed or reordered. It is good enough to ship to a
  dashboard — see `tools/export_to_langfuse.py` — and not good enough to be
  evidence.
- **No enforced spend ceiling.** `budget` in the config is advisory. The
  orchestrator states the implied call count up front and you decide there.
- **No input validation and no output escaping.** A paragraph beginning `## `
  becomes a chapter heading in `dist/book.md`. See `SECURITY.md`.
- **It does not run unattended.** No headless entry point, so no CI, no cron, no
  server. A person drives it.

## Layout

```
.claude/agents/           the eight subagents — prompts and tool lists
.claude/skills/novaforge/ SKILL.md, the orchestration procedure
specs/flow.yaml           the six stages, their order and failure policy
specs/agents/             one spec per agent, with traced AGT-* requirements
specs/acceptance.md       ACC-1..ACC-11, each marked with how it is established
specs/CONFIG-SPEC.md      CFG-1..CFG-12, two of them withdrawn
specs/changes/            CHG-001..CHG-003, including this refactor
config/                   the base config and four profiles
tools/                    export_to_langfuse.py, ships a finished run to Langfuse
docs/                     the pipeline diagram
SECURITY.md               six layers, compared against main line by line
```

## Where to read next

1. `.claude/agents/chapter-writer.md` — the tool list, and why it is the point.
2. `.claude/skills/novaforge/SKILL.md` — the procedure, end to end.
3. `specs/changes/CHG-003-claude-as-orchestrator.md` — what this cost.
4. `specs/acceptance.md` — what is actually established, and what is not.

## Licence

MIT.
