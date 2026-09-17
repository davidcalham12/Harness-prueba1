# CHG-003 — Claude Code as the orchestrator, the agents as subagents

**Status:** open, and branch-scoped. This change exists on `claude-orchestrator`
only. `main` is untouched and still holds the Python implementation.

## What changed

The Python package that ran the pipeline was deleted, and the procedure it
implemented moved into `.claude/skills/novaforge/SKILL.md`, which Claude Code
follows. The eight agents moved from `.claude/skills/<name>/SKILL.md` — prompts
loaded and sent by Python — to `.claude/agents/<name>.md`, which are Claude Code
subagents dispatched with the Agent tool.

Deleted: `novaforge/` (49 files, 7,184 lines), `tests/` (30 files, 5,453 lines),
`tools/`, `output/golden-tiny/` (34 files), `pyproject.toml`, `RUNBOOK.md`.
Kept and rewritten: `specs/`, `config/`, `README.md`, `SECURITY.md`, the diagram.

Roughly 14,000 of 16,400 lines went.

## Why

Two reasons, and only the first is a real argument.

**The context policy became structural.** The claim the project is built on is
that the chapter writer never sees a previous chapter's prose. On `main` that is
a runtime assertion: `assert_no_prior_prose` re-reads the assembled prompt before
it is sent and raises if ten consecutive words from an earlier chapter leaked in.
It is a good check and it is still a check — something that runs after the fact
and could be removed without the architecture noticing.

Here the `chapter-writer` subagent runs in its own context window and its tool
list is `Glob`, which returns paths and cannot return file contents. The prose is
not merely absent from the prompt; it is unreachable. A guarantee held by a
capability is a different kind of claim from one held by an assertion, and this
is the project's central claim.

**The engine layer stopped earning its place.** `novaforge/engines/` existed to
simulate what Claude Code does natively. On `main` the shipping engine is `mock`,
and `--engine anthropic` was never implemented — so the one thing the project
claims to do, turn a premise into a novel, was the one thing never demonstrated.
Here a real model writes from a real premise on the first run.

## What it cost

Recorded here in full, because a change record that lists only the upside is
advocacy.

- **The 810 tests.** They tested Python that no longer exists. Nothing replaces
  them; there is no unit test for "the orchestrator followed the procedure".
- **Determinism, and `output/golden-tiny/`.** The committed byte-for-byte fixture
  is gone. It was not a test of quality — it was the mechanism that caught
  changes nobody thought to write a test for, and three of this project's real
  defects were found by regenerating it and reading the diff.
- **Two of the four critics stopped being reproducible.** `continuity` and
  `science` are models now. The same draft can clear the gate one run and not the
  next, so "it passed the gate" is a statement about one run. `length` and
  `chatter` are still arithmetic and still reproduce.
- **The tamper-evident audit chain**, the pre-call budget ceilings, the input
  validation, the output escaping and the redactor. See `SECURITY.md` for the
  layer-by-layer account: one row improved, five got worse.
- **The Langfuse integration**, built and verified against a live project the
  same week this branch was cut — traces, scores, and prompt management with the
  prompt files as fallback. It hung off the Python orchestrator's single `_call`
  funnel and went with it.
- **Headless operation.** `python -m novaforge` ran in a shell, a cron job or
  CI. This is a procedure a person drives inside Claude Code.
- **PDF export.** `novaforge/export/pdf.py` wrote A5 pages against real Helvetica
  metrics with no dependency. `outputs.formats` is `["markdown"]` here.

## The honest summary

This is not a refactor. It is a second implementation of the same spec, sharing
the prompts, the flow and the config, that trades verification for structural
isolation and for actually writing a novel.

Which branch is right depends on what is wanted. **An auditable harness that runs
unattended: `main`.** **A demonstration of multi-agent orchestration whose
central guarantee is a capability rather than a promise: this one.**

## What would close this

Nothing needs to. A branch is allowed to be a branch. But three things would make
it defensible as a replacement rather than an alternative:

1. A rejection that is guaranteed rather than hoped for, so ACC-2 means something
   again.
2. Hash-chaining `logs/agents.jsonl`, which needs no Python package — a hook
   could do it.
3. Re-escaping prose before it is concatenated into `dist/book.md`, because a
   paragraph beginning `## ` currently becomes a chapter heading (SEC-5).
