# NovaForge

A spec-driven multi-agent harness that writes science-fiction novels.

Eight agents, a quality gate that rejects its own drafts, and a context policy
that keeps the prompt the same size at chapter 34 as at chapter 1. It runs
offline and for free on a deterministic mock engine, so you can see the whole
pipeline work before spending anything.

```bash
python -m novaforge new "A deep-space salvage crew finds a derelict that remembers them" --profile tiny --engine mock
```

No dependencies. Python 3.10 or newer, and that is the whole list.

> **Read this before the demo output below.** The mock engine **ignores your
> premise**. Ask it for a medieval blacksmith and you get the same deep-space
> salvage crew as everyone else — the cast, the outline and every chapter are
> identical whatever you type. That is deliberate: `output/golden-tiny/` is a
> fixture a fresh run must reproduce byte for byte, and an engine whose output
> depended on its input could not be one.
>
> So a mock run shows you **the pipeline working, not the writing**. Everything
> below about the gate, the context policy and the audit chain is real and
> exercised. Whether this harness turns *your* premise into *your* novel is a
> question only `--engine anthropic` can answer, and that engine is not written
> yet.

## What a run looks like

```
NovaForge: A deep-space salvage crew finds a derelict that remembers th  [hard-scifi, 3 chapters]
  profile tiny     config 58b26878bd29
  spec    specs/flow.yaml
  engine  mock / claude-opus-5
  length  300-550 words per chapter, wrapped at 64
  gate    continuity+science+length+chatter >= 8, 2 rewrites allowed, on_fail=accept_with_warnings
  budget  $5.00, 120 calls, 1,000,000 tokens

  [1/6] FLOW-1 worldbuild -> worldbuilder
    wrote bible/world.md (234 words, 4 rules)
  [2/6] FLOW-2 characters -> character_architect
    wrote bible/characters.md (45 words, 4 characters)
    ...
  [4/6] FLOW-4 chapters -> chapter_writer
    gate continuity+science+length >= 8, max 3 drafts, on_fail=accept_with_warnings
    ch01 draft 1: continuity 10/10, length 10/10, science 10/10 -> accept
    ch02 draft 1: continuity  6/10, length 10/10, science 10/10 -> retry
      [continuity] name-drift: 'Kassar'
    ch02 draft 2: continuity 10/10, length 10/10, science 10/10 -> accept
    ch03 draft 1: continuity 10/10, length 10/10, science 10/10 -> accept
  ...
  [6/6] FLOW-6 publish -> publisher
    wrote dist/book.md — 3 chapters, 1,270 words, wrapped at 64 columns
    wrote dist/book.pdf — 7 pages, A5, 10pt Helvetica, 7,356 bytes

  audit     chain intact (31 rows, hash chain)
```

**Two lines in that output matter more than the rest.**

`ch02 draft 1 ... -> retry` is the gate firing. The Continuity Critic found
`Kassar` where the Story Bible says `Kassab`, quoted it back to the writer, and
the second draft came back clean. The mock engine misspells a surname in the
first draft of every even-numbered chapter *on purpose* — a run where every
chapter passed first time would demonstrate nothing about the gate.

`length 10/10` is the one critic that is not a model at all. It is arithmetic
against the band in the config, which is what makes `words_per_chapter` a
setting rather than a suggestion.

## The idea

A novel does not fit in a context window, and the usual answer — feed the model
more of what it already wrote — gets slower and vaguer with every chapter.

NovaForge takes the opposite approach. **The chapter writer never sees a
previous chapter's prose.** It gets the Story Bible, its own outline entry, and
a rolling summary capped at a configured word count. Nothing else. The prompt
for chapter 34 is the same size as the prompt for chapter 1.

That only works if two things hold, so both are enforced rather than requested:

- **Continuity comes from the Bible, not from memory.** The Story Bible is the
  single shared state, and the critics hold every draft against it.
- **The policy is checked, not trusted.**
  `novaforge/context.py:assert_no_prior_prose` re-reads the assembled prompt
  before it is sent and raises if any ten-word run from an earlier chapter
  leaked in.

## Three files own the pipeline. None of them is Python.

| File | Owns | Change it to… |
| --- | --- | --- |
| `specs/flow.yaml` | **Structure** — which stages exist, their order, which may write the Bible | reorder or add a stage |
| `config/novel.config.json` | **Numbers** — lengths, gate threshold, draft allowance, budget | write a longer book, or a stricter one |
| `.claude/skills/*/SKILL.md` | **Prompts** — what each agent is told | change how an agent writes |

`novaforge/orchestrator.py` loads `flow.yaml` and executes it. There is no stage
list in the Python, no threshold literal, and no prompt. That is checked, not
promised: `tests/test_agents.py` fails if a stage module contains a prompt, and
`tools/check_specs.py` fails if a stage names an agent with no skill, if a skill
contradicts its spec, or if a declared requirement has no test citing it.

```bash
python tools/check_specs.py
# specs OK: 8 agent specs, 8 skills, 16 requirements, all traced
```

## The agents

Six run as stages, two are critics.

| Agent | Stage | Writes the Bible |
| --- | --- | --- |
| `worldbuilder` | FLOW-1 | yes |
| `character_architect` | FLOW-2 | yes |
| `plot_architect` | FLOW-3 | no |
| `chapter_writer` | FLOW-4 | no |
| `style_editor` | FLOW-5 | no |
| `publisher` | FLOW-6 | no |
| `continuity_critic` | FLOW-4 gate | no |
| `science_critic` | FLOW-4 gate | no |

Only two may write the Story Bible. The other six are handed a reader object
with no `write` method at all, and a runtime check keyed on the role the
*orchestrator* invoked — never on anything a model said about itself. A skill
file cannot grant itself access by editing its own front matter; the run
refuses to start if a skill and `flow.yaml` disagree.

## Try it

```bash
python -m pytest -q                  # 805 tests, ~52 seconds
python tools/check_specs.py          # specs, skills and tests still agree
python -m novaforge new "your premise here" --profile tiny --engine mock
python -m novaforge status <slug>
python -m novaforge resume <slug>
```

Four profiles, from a three-chapter demo to a full novel:

| Profile | Chapters | Words each | Budget |
| --- | --- | --- | --- |
| `tiny` | 3 | 300–550 | $5 |
| `small` | 8 | 900–1400 | $25 |
| `medium` | 18 | 1600–2400 | $60 |
| `full` | 34 | 2200–3200 | $120 |

Useful flags: `--chapters`, `--words`, `--wrap`, `--threshold`,
`--max-revisions`, `--max-cost-usd`, `--max-calls`, `--seed`, `--no-drift`,
`--force`. Every one of them is a config key arriving by a different route.

## What you get

```
output/<slug>/
  bible/            world, characters, timeline, mysteries — the shared state
  outline.md        acts, tension curve, reader promises
  chapters/         chNN.md (approved), chNN.final.md (styled), chNN.summary.md
  critiques/        every draft's verdict, including the ones that were rejected
  dist/             book.md and book.pdf
  logs/             agents.jsonl (hash-chained) and cost.json
  state.json        resume from here
  config.snapshot.json
```

`output/golden-tiny/` is a complete run, committed, so you can read the output
without running anything. Start at `critiques/ch02.continuity.json`: it holds
the rejected first draft's verdict alongside the accepted one, which is the
gate's own record of having done something.

## Safe by construction, where it can be

`SECURITY.md` has the full model. In short: every write goes through a
workspace bounded by `output/<slug>/` and checked after `realpath`; every piece
of model-written text reaches another agent inside a labelled `<untrusted>`
block whose delimiters cannot be closed from inside; spend ceilings are checked
*before* each call, not after; and `logs/agents.jsonl` chains each row to the
hash of the one before it.

That last one is tamper-**evident**, not tamper-**proof** — anyone who can
rewrite the whole file can recompute every hash. Set `NOVAFORGE_AUDIT_KEY` and
it becomes an HMAC chain instead.

```bash
python -c "from novaforge.security.audit import AuditChain; from novaforge.security.sandbox import Workspace; print(AuditChain(Workspace('output/golden-tiny', create=False)).verify())"
# chain intact (31 rows, hash chain)
```

## Langfuse

The project has moved to Langfuse for two things: **observing runs** and
**managing prompts**.

```powershell
pip install "novaforge[langfuse]"
$env:LANGFUSE_PUBLIC_KEY = "pk-lf-..."
$env:LANGFUSE_SECRET_KEY = "sk-lf-..."
# pick your region; either name works
$env:LANGFUSE_BASE_URL   = "https://us.cloud.langfuse.com"

python tools\push_prompts.py --push          # seed the 8 prompts
python -m novaforge new "your premise" --profile tiny --engine mock
```

One trace per run, one generation per model call, one score per critic verdict.
That mapping is not a design decision so much as a recognition: the audit log
already had exactly those three shapes.

**Two things did not move, and the reasons are in `specs/CONFIG-SPEC.md`
§ CFG-11 and § CFG-12.**

`logs/agents.jsonl` is still written and still hash-chained. A trace in a
hosted service is a row in somebody's database and can be edited; the file on
disk can be verified. Langfuse is where a run is *looked at*; the chain is
where it is *proved*.

`.claude/skills/` still holds the prompts, now as the fallback rather than the
source. Langfuse's own `get_prompt` takes a fallback argument, because a prompt
service being unreachable should not stop the thing it serves. Those files are
also what `tools/check_specs.py` reads to trace 41 requirements — and **only
wording moved**: role, model and `writes_bible` are never read from Langfuse,
because a service that could grant Story Bible access by editing a prompt would
make SEC-4.3 a suggestion.

**Without credentials everything still runs.** Prompts come from the files, no
trace is sent, and the run says so in one line. Set `observability.sink` to
`"none"` and `agents.prompt_source` to `"file"` for the fully offline
configuration the project shipped with.

## Adding an agent

A new agent with an existing shape needs no Python at all:

1. Add a stage to `specs/flow.yaml` pointing at an existing `impl`.
2. Write `.claude/skills/<name>/SKILL.md` — front matter plus a
   `## System prompt` section.
3. Write `specs/agents/<name>.md` with its requirements.
4. Write a test citing each requirement's identifier.
5. `python tools/check_specs.py`

A genuinely new *kind* of step — not a new agent with an existing shape — needs
one class and one entry in `novaforge/stages/__init__.py`. A new critic is one
class and one entry in `novaforge/critics/__init__.py`, plus its name in
`quality_gate.critics`.

## Layout

```
novaforge/
  composition.py      the only place concrete classes are wired together
  orchestrator.py     loads flow.yaml and runs it
  agents.py           reads SKILL.md files
  config.py           layers base → profile → --config → flags
  context.py          what the writer may see, and proof of what it may not
  bible.py            the only shared state; two classes, one with no write()
  stages/             one class per `impl` in the flow spec
  critics/            continuity, science, length
  engines/            mock (deterministic, free); anthropic is not yet written
  export/             markdown and pdf, both written from scratch
  security/           validation, secrets, sandbox, prompting, escaping, audit
  spec/               a YAML parser for the subset flow.yaml uses
```

## What is not done yet

Stated plainly, because a README that implies otherwise is the most expensive
kind of documentation:

- **`--engine anthropic` is not implemented**, so the central claim — that this
  turns a premise into a novel — is the one thing here that has never been
  demonstrated. The mock ignores the premise by design, so no mock run can
  demonstrate it. Everything *around* that claim is tested; the claim itself
  waits on an API key.
- **Two escapers are kept but unused.** All six security layers ship, but
  `xml_escape` and `svg_text` in SEC-5 are on no code path: CHG-001 removed the
  EPUB and the SVG cover. They are tested anyway, because an untested escaper
  is worse than none, and a test asserts they really are unused.
- **The two critics are scored in code, not by a model.** `docs/novaforge_flow.mermaid`
  shows them as model-driven, and their prompts exist; this build evaluates them
  deterministically so a mock run stays reproducible and `output/golden-tiny/`
  stays diffable. Their skills declare `shipping: false` and `check_specs.py`
  reports it rather than hiding it.

## Where to read next

- `RUNBOOK.md` — every command, what to expect, and what to look at afterwards
- `specs/acceptance.md` — what has to be true for this to be doing what it claims
- `specs/CONFIG-SPEC.md` — the configuration layer and the rules it enforces
- `SECURITY.md` — the six layers, and what each one explicitly does *not* cover
- `specs/flow.yaml` — the pipeline itself, which is the thing that actually runs
- `docs/novaforge_flow.mermaid` — the same pipeline as a diagram

## Licence

MIT.
