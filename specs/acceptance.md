# Acceptance criteria

What has to be true for this project to be doing what it claims.

**Status: this branch has no automated verification.** On `main`, every
criterion below was checked by a test and the table at the bottom named which
one. That test suite does not exist here — it tested a Python package this
branch deleted — so each criterion is now marked with how it is actually
established: **held by construction**, **checked by the orchestrator**, or
**unverified**.

Read the third category as what it says. An unverified criterion is not a
criterion that passes quietly; it is one nobody is checking.

---

## ACC-1 — The pipeline runs end to end

*Checked by the orchestrator.*

Invoke the `novaforge` skill with a premise and a profile. Six stages execute in
the order `specs/flow.yaml` declares them, and the run ends having written
`output/<slug>/dist/book.md`.

It needs a network and a Claude Code session. The offline, free, dependency-free
run is gone with the mock engine, and so is `dist/book.pdf` — PDF export was a
Python module.

## ACC-2 — The quality gate rejects and repairs

*Unverified.*

Not merely "the gate exists": at least one chapter should be **rejected and
redrafted**, because a run where everything passes first time demonstrates
nothing about the gate.

On `main` this was guaranteed — the mock engine misspelled a canonical surname
in the first draft of every even-numbered chapter, so the rejection was certain
and reproducible. Here the critics are models judging real prose, so a run may
legitimately have nothing to reject. **The absence of a rejection is no longer
evidence that the gate is broken, and its presence is no longer evidence that it
works.** That is a real loss of signal, not a detail.

## ACC-3 — The rejected draft's verdict survives

*Checked by the orchestrator.*

When a draft is rejected, `critiques/chNN.<critic>.json` keeps every iteration —
the failing score and its quoted findings, not only the accepted one.

The evidence that the gate did something is the thing worth keeping. A run that
recorded only its accepted drafts would be a run that cannot show its own
reasoning.

## ACC-4 — The writer never receives prior chapter prose

*Held by construction, and this one got stronger.*

On `main` this was a runtime assertion: `assert_no_prior_prose` re-read the
assembled prompt and raised if ten consecutive words from an earlier chapter had
reached it. It was a good check, and it was still a check — something that ran
after the prompt was built and could be removed.

Here it is a capability. The `chapter-writer` subagent runs in its own context
window, so no earlier chapter is behind it, and its tool list is `Glob` alone.
`Glob` returns file paths and cannot return file contents, so `chapters/ch01.md`
is unreachable to it even deliberately.

The orchestrator still has to do its half — assemble the prompt from the Bible,
one outline entry and a capped summary — and nothing checks that it did. So:
**the agent cannot go and fetch prose; the orchestrator could still hand it
some.** Half of this is now structural and half is now unverified, where before
both halves were asserted at runtime.

## ACC-5 — Length is measured, not asserted

*Checked by the orchestrator.*

The `length` critic is arithmetic — `wc -w` in the shell — not a model. That is
what makes `novel.words_per_chapter` a setting rather than a suggestion: a draft
outside the band is sent back regardless of how good it is. The same is true of
`chatter`, which is a scan for a heading, and of the style pass's word-count
comparison.

These three are the only parts of the gate that survive the migration intact,
and they survive precisely because they were never model judgements.

## ACC-6 — A run is reproducible

*Withdrawn. This branch does not claim it.*

Two runs of the same premise will not produce the same book, and two runs over
the same draft will not necessarily produce the same verdict. `output/golden-tiny/`
— the committed, byte-for-byte fixture that was the proof — is deleted here.

This is the single largest thing given up, and it is worth being precise about
why it mattered: the fixture was not a test of output quality, it was the
mechanism that caught changes nobody thought to write a test for. Regenerate,
diff, and anything that moved showed up. Three of this project's real defects
were found that way.

`main` still has it.

## ACC-7 — A run resumes at chapter granularity

*Unverified.*

`state.json` is written after each chapter and the skill says to resume from the
last accepted one. Nothing enforces it, and there is no `--resume` whose
behaviour can be pinned.

## ACC-8 — The run can be reconstructed afterwards

*Weakened, and no longer what the word "audit" implies.*

`logs/agents.jsonl` gets one row per subagent call. It is **not hash-chained**.
Nothing detects a row edited, removed, inserted or reordered. On `main` this was
tamper-evident — and even there it was tamper-*evident*, never tamper-*proof*.
Here it is neither: it is a convenience log.

The Claude Code session transcript is a second record, and a more complete one,
but it is not designed as an audit trail either.

## ACC-9 — Spend is bounded before it happens

*Withdrawn. This branch does not claim it.*

`budget.max_cost_usd` and `max_calls` are in the config but nothing checks them
before a call. The orchestrator states the implied call count in its plan and
the operator decides there. A `full` run is thirty-four chapters through a
four-critic gate, so that decision matters.

## ACC-10 — Structure, numbers and prompts live outside the procedure

*Held by construction.*

`specs/flow.yaml` owns stage order and failure policy, `config/*.json` owns the
numbers, and `.claude/agents/*.md` owns the prompts. `SKILL.md` is a procedure
that reads all three; it contains no stage list and no threshold of its own.

What is gone is the *enforcement*: `tools/check_specs.py` used to fail if a stage
named an agent with no skill, if a skill contradicted its spec, or if a declared
requirement had no test citing it. Nothing fails now. Drift between
`specs/flow.yaml` and `.claude/agents/` will simply happen, silently, and a
reader has to catch it.

## ACC-11 — What is not claimed

Stated so the criteria above are not read as covering more than they do.

- **Nothing here is automatically verified.** There is no test suite. Every
  "checked by the orchestrator" above means a procedure says to check it.
- **The gate is not reproducible**, because two of its four critics are models.
  "It passed the gate" is a statement about one run, not a property of the text.
- **There is no tamper-evident record and no enforced ceiling on spend.**
- **It does not run unattended.** No headless entry point, so it will not run in
  CI, on a schedule, or on a server.
- The manuscript in `dist/` is not redacted, and there is no input validation
  refusing a premise that carries a credential. On `main`, SEC-1 did that.

One claim this branch makes that `main` could not: the mock engine ignored the
premise entirely, so no criterion on `main` was evidence that the harness turns a
premise into a novel. Here a real model writes from a real premise. **The thing
the machinery exists to serve is finally demonstrable — and almost all the
machinery that guarded it is gone.** That is the trade, stated in one sentence.

---

## Where these are checked

| Criterion | How |
| --- | --- |
| ACC-1 | run the skill and look at `dist/book.md` |
| ACC-2 | unverified |
| ACC-3 | `critiques/*.json` after a run with a rejection |
| ACC-4 | `tools: Glob` in `.claude/agents/chapter-writer.md` — read it |
| ACC-5 | `wc -w` over `chapters/*.md` against the merged config band |
| ACC-6 | withdrawn |
| ACC-7 | unverified |
| ACC-8 | `logs/agents.jsonl` exists; its integrity is not checked |
| ACC-9 | withdrawn |
| ACC-10 | read `SKILL.md` and confirm no threshold is written in it |

Every row that says "read it" is a row where a human is the check. That was
true of nothing on `main`.
