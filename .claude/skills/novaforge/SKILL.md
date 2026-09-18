---
name: novaforge
description: Write a novel from a premise by orchestrating the eight NovaForge subagents through the six stages of specs/flow.yaml, with a per-chapter quality gate. Use when asked to draft, generate or continue a NovaForge novel, or when asked to run a stage of the pipeline.
---

# NovaForge — the orchestration procedure

You are the orchestrator. The eight agents in `.claude/agents/` are subagents
you dispatch with the Agent tool. This file is the procedure; `specs/flow.yaml`
is the contract it implements.

**Read `specs/flow.yaml` and the config before you start.** They are not
decoration — the stage order, the gate thresholds and every number below come
from them, and they may have changed since this file was written. Where this
file and the spec disagree, the spec wins and you should say so.

## 0. Set up the run

Ask for, or take from the request:

- **the premise** — one or two sentences
- **the profile** — `tiny` (3 chapters), `small` (8), `medium` (18), `full` (34)

Then:

1. Read `config/novel.config.json`, then read `config/profiles/<profile>.json`
   and overlay it. A profile is partial: it states what it changes and nothing
   else, so overlay key by key rather than replacing whole sections.
2. Derive a slug from the premise — lowercase, hyphenated, at most 40
   characters — unless one was given.
3. Create the workspace: `output/<slug>/` with `bible/`, `chapters/`,
   `critiques/`, `dist/` and `logs/`.
4. Write the merged configuration to `output/<slug>/config.snapshot.json`. A run
   nobody can reconstruct the settings of is a run nobody can explain.
5. Write `output/<slug>/state.json` with the premise, the profile, the slug and
   an empty `chapters` list.

**Tell the user the plan before you spend anything**: the profile, the chapter
count, the target words per chapter and how many subagent calls that implies.
A `full` run is thirty-four chapters through a gate — it is not a thing to start
by accident.

## 1. FLOW-1 — worldbuild

Dispatch `worldbuilder`. Its prompt must carry, because it has no Read tool:

- the premise, verbatim
- `novel.tone`, `novel.chapters`
- the counts from `bible`: `factions`, `technology_entries`, `world_rules`,
  `world_min_words`, `world_max_words`
- the absolute path of the workspace, so it can write `bible/world.md`

When it returns, read `bible/world.md` yourself and check the `## Rules` heading
exists with at least `bible.world_rules.min` bullets under it. If it does not,
dispatch again with that as the correction. Nothing downstream can recover a
missing rules section: the science critic reads from under that heading and
nowhere else.

## 2. FLOW-2 — characters

Dispatch `character-architect`. Its prompt must carry the **full text of
`bible/world.md`** — it has no Read tool either — plus the premise, the tone,
and the counts for `characters`, `timeline_rows` and `mysteries`.

It returns the canonical character names. **Keep that list.** Every later prompt
carries it, and it is what the continuity critic checks spelling against.

## 3. FLOW-3 — outline

Dispatch `plot-architect` with all four Bible files quoted in full, the chapter
count, the canonical names, and `novel.promises` and `novel.beats_per_chapter`.

It returns the outline as text. **You** write it to `output/<slug>/outline.md`.

Then split it on `### Chapter N — Title` and keep one entry per chapter. If the
split yields fewer entries than `novel.chapters`, the outline is malformed —
dispatch again rather than writing chapters from nothing. Anything other than
that exact heading shape, `**Chapter 1: Title**` most often, breaks the split.

## 4. FLOW-4 — chapters, with the gate

For each chapter `n` from 1 to `novel.chapters`:

### Assemble the writer's context — and nothing more

The prompt for `chapter-writer` contains exactly:

- the four Bible files, in full
- **this chapter's outline entry only**
- the rolling summary, capped at `context.max_summary_words` words
- the canonical character names
- the chapter number, its title, and `novel.words_per_chapter.target`

**It never contains a previous chapter's prose.** That is the architectural claim
of the project. Here it holds for two reasons that are worth keeping separate:
you do not put prose in the prompt, and the subagent has only `Glob`, which
returns paths and cannot return contents — so the guarantee does not rest solely
on your discipline. Do not add `Read` to that agent to make something easier.

### Run the gate

The critics are `quality_gate.critics` in the config. Run them on the returned
draft:

| critic | who runs it | how |
|---|---|---|
| `length` | **you** | count words in the shell; score 10 inside the band, 0 outside |
| `chatter` | **you** | scan for preamble; score 0 if the draft does not begin with `# Chapter` |
| `continuity` | subagent | dispatch `continuity-critic` with the draft and the Bible |
| `science` | subagent | dispatch `science-critic` with the draft and `bible/world.md` |

Dispatch the two critic subagents **in the same message** so they run
concurrently. They are independent, and running them in series doubles the wall
clock of every chapter.

Count words with a command, never by eye:

```bash
wc -w < output/<slug>/chapters/ch0N.md
```

The band is `words_per_chapter.min` to `.max`, widened by `tolerance_pct`.

Aggregate with `quality_gate.aggregate` — `min`, so **a chapter is only as good
as its worst critic**. If the aggregate is at or above `quality_gate.threshold`,
accept. Otherwise redraft, following the four rules below.

`quality_gate.max_revisions` is the number of *rewrites*, so 2 means up to three
drafts. When drafts run out, apply `on_fail` from `flow.yaml` for FLOW-4:
`accept_with_warnings` — keep the best draft, and record the warning where the
user will see it.

### Four rules for the redraft, each of which was once got wrong

These were found by running the pipeline, not by reading it. Every one of them
made the gate weaker in a way that looked like it was working.

**1. Hand back the draft, not only the findings.** A redraft prompt that carries
the findings without the text they quote is asking for "repair these and change
nothing else" when there is nothing to change — so the writer starts a fresh
chapter each round, against findings quoting text that is no longer in it, and a
rewrite can come back worse than what it replaced.

This is not a hole in the context policy, and the distinction is the whole
point: the policy forbids a **previous chapter's** prose. This is the writer's
own rejected draft of the chapter it is writing now.

**2. Ask for substitutions, not for a chapter.** Rather than the whole chapter
back, ask for the exact sentences to replace:

```json
{"patches": [{"find": "<text copied EXACTLY from the draft>",
              "replace": "<the corrected text>",
              "why": "<which finding this addresses>"}]}
```

Apply them yourself, matching `find` literally. Two things follow: anything the
findings do not name **cannot** change, because you do not touch it; and "was
this finding addressed" stops being a judgement — either the quoted text is
still there or it is not. A `find` that does not match is skipped and counted,
never applied approximately. If no patch applies at all, fall back to a full
rewrite rather than burning the attempt on nothing, and record which happened.

**3. A critic that returns no usable verdict is excluded, never counted as a
pass.** If `continuity-critic` or `science-critic` comes back with something you
cannot parse as a score, do not substitute one: 10 invents an approval and 0
invents a rejection. Leave it out of the `min`, record it as unscored, and say
so in the gate row's `note`. A gate running on three critics is weaker than one
running on four, and that is the truth of what happened.

**4. Keep the best draft, not the last.** Track the highest aggregate as you go.
A chapter whose first draft scored 7 and whose third scored 4 must ship the 7 —
a rewrite is not guaranteed to be an improvement and the gate must not assume it
was. An *accepted* draft is the one that passed, which is not always the best.

Two things that cost nothing and are worth doing. Tell the writer when it is on
its last allowed draft, because one that knows it spends its effort on the
findings rather than on flourishes. And after a redraft, check whether the
quoted passages are still present verbatim — if one survived, the repair did not
happen, and that is arithmetic rather than judgement.

### Record it

Write, for each chapter:

- `chapters/ch0N.md` — the accepted draft
- `chapters/ch0N.summary.md` — a summary you write, under
  `context.max_summary_words`, which becomes part of the next chapter's rolling
  summary. This is the only channel between chapters, so it carries what a later
  chapter cannot be written without: what changed, who now knows what, and what
  is still open.
- `critiques/ch0N.<critic>.json` — every iteration's score and findings, not just
  the last. **The rejected draft's critique is the evidence that the gate did
  something**, and it is the first thing worth opening when someone asks whether
  this pipeline is real.

Append one row per subagent call to `logs/agents.jsonl`: timestamp, stage, agent,
chapter, iteration, verdict. Update `state.json` after each chapter so an
interrupted run can be resumed from the last accepted one rather than restarted.

**Record `tokens` and `model` on every agent row, for every stage.** The Agent
tool reports `subagent_tokens` in its result, and a task notification repeats it;
take the figure from there and write it down. `model` is the `model:` line in
that agent's `.claude/agents/<name>.md`.

Three things about that figure, because getting them wrong makes the numbers
worse than absent:

- **It is cumulative across a resume.** An agent sent back for a redraft reports
  the running total for the whole agent, not the cost of the second attempt. Log
  the *difference* from its previous total, so each row is one attempt.
- **It is a single total**, with no input/output split. Do not invent one.
- **A blocked or wasted call still costs.** Log it with its tokens and the reason
  it produced nothing. The first run of this pipeline spent 17,479 tokens on a
  rewrite the Write tool refused, and that is exactly the kind of number a
  dashboard exists to surface.

Without these fields `tools/export_to_langfuse.py` ships the run with no usage
and no cost, and there is nothing to observe.

## 5. FLOW-5 — style

For each approved chapter, dispatch `style-editor` with the chapter text.

**Check its work with arithmetic.** Count the words in what it returns and
compare with what you sent. If the counts differ, the pass rewrote something —
discard it and copy the unedited chapter to `ch0N.final.md` instead, and tell the
user which chapters that happened to. The published text must be the text the
gate approved.

## 6. FLOW-6 — publish

Dispatch `publisher` with the Bible, the outline and the chapter summaries — not
the chapters; a synopsis is written from canon. Give it
`outputs.synopsis.words.min/max` and `comparables`. Write the result to
`synopsis.md`.

Then **assemble `dist/book.md` yourself**, in the shell, by concatenating the
`.final.md` files in order with the synopsis in front if
`outputs.markdown.include_synopsis` is true. Do not ask a subagent to do this.
Concatenation is a mechanical transformation, and a model asked to perform one
will paraphrase a sentence in the middle that the gate already approved.

PDF export is not available in this architecture — it was a Python module, and
`outputs.formats` reads `["markdown"]` here. If a config asks for `pdf`, say so
plainly rather than producing something and calling it a PDF.

## 7. Report

Tell the user: the workspace path, chapters approved versus accepted with
warnings, total words, and the path of any chapter whose style pass was
discarded. Then name the file worth opening first — a `critiques/*.json` from a
chapter that was rejected once, because that is what shows the gate working.

---

## What this architecture does not give you

State these when a reader asks what the pipeline guarantees. They are honest
limits, not caveats to bury.

**The gate is not reproducible.** Two of the four critics are models. The same
draft can score 8 one run and 7 the next, so "it passed the gate" is a statement
about one run and not a property of the text. The `length` and `chatter` critics
*are* arithmetic and do reproduce.

**There is no tamper-evident audit.** `logs/agents.jsonl` is a record you write,
not a hash chain, and anyone who can edit the file can edit it undetectably.

**There is no enforced budget ceiling.** Nothing stops a run before it spends.
Read the call count out of the plan in step 0 and decide there.

**It does not run unattended.** This is a procedure a person drives inside Claude
Code. It has no headless entry point and will not run in CI.

The `main` branch of this repository holds the Python implementation, which has
all four of those and a byte-reproducible fixture. If what you need is an
auditable harness that runs on its own, that branch is the one — this one trades
those properties for subagents whose isolation is structural rather than
asserted.
