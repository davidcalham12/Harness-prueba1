# Acceptance criteria

What has to be true for this project to be doing what it claims. `RUNBOOK.md`
is the operator's version of this file — the commands to type and what to look
at; this is the list those commands are checking.

**Status: all criteria below pass.** They did not when this file's identifiers
were first cited: the session that assembled the repository had no working
shell, so every one of them was a prediction. `specs/changes/` records that.

---

## ACC-1 — The pipeline runs end to end, offline and free

```bash
python -m novaforge new "<premise>" --profile tiny --engine mock
```

Six stages execute in the order `specs/flow.yaml` declares them, and the run
exits 0 having written `dist/book.md` and `dist/book.pdf`. No network, no
credential, no dependency outside the standard library.

## ACC-2 — The quality gate rejects and repairs

Not merely "the gate exists". At least one chapter must be **rejected and
redrafted** in a demo run, because a run where everything passes first time
demonstrates nothing about the gate.

The mock engine misspells a canonical surname in the first draft of every
even-numbered chapter, controlled by `engine.inject_drift`. In the tiny
profile that means `ch02 draft 1 -> retry`, then `ch02 draft 2 -> accept`.

## ACC-3 — The rejected draft's verdict survives

`critiques/ch02.continuity.json` holds `iterations[0]` with a `name-drift`
finding quoting the drifted surname, and `final.findings` empty.

The evidence that the gate did something is the thing worth keeping. A run that
recorded only its accepted drafts would be a run that cannot show its own
reasoning.

## ACC-4 — The writer never receives prior chapter prose

FLOW-4's `context_policy` is enforced at runtime, not requested in a prompt.
`novaforge/context.py:assert_no_prior_prose` re-reads the assembled prompt
before it is sent and raises if any run of `context.leak_window_words`
consecutive words from an earlier chapter reached it.

Stated exactly: *no run of ten consecutive words from an earlier chapter
reaches the writer, unless that run is also in the canon the writer is entitled
to see.* The canon exemption is necessary — without it, a chapter that quoted a
world rule would make that rule unquotable for every later chapter.

## ACC-5 — Length is measured, not asserted

Every approved chapter falls inside `novel.words_per_chapter`. The Length
Critic is arithmetic rather than a model, which is what makes that band a
setting instead of a suggestion: a draft outside it is sent back regardless of
how good it is.

## ACC-6 — A run is reproducible

Two runs of the same command with the same config produce byte-identical
artefacts, in separate processes and on separate machines.

`output/golden-tiny/` is the committed proof. The only fields that differ
between regenerations are `ts` and `elapsed_s` in the audit log, and the `hash`
and `prev` derived from them — one reason, not two, since the chain hash covers
the timestamp.

## ACC-7 — A run resumes at chapter granularity

Deleting one chapter and marking it `pending` costs one chapter to repair, not
a whole run. The documented repair in `RUNBOOK.md` § 5 re-runs FLOW-4 through
FLOW-6 and rewrites **only** chapter 3; the other two are reloaded without a
model call.

Resume recovers its config from `config.snapshot.json` rather than from flags,
so forgetting `--profile tiny` cannot continue a three-chapter book as a
twelve-chapter one.

## ACC-8 — The run can be reconstructed afterwards

`logs/agents.jsonl` carries one row per model call, each naming its `flow_id`
and `config_hash`, plus `gate_decision` rows saying why each chapter was
accepted and `bible_write` rows saying who wrote canon.

The chain is hash-linked and `verify()` reports any row edited, removed,
inserted or reordered. It is tamper-**evident**, not tamper-**proof**.

## ACC-9 — Spend is bounded before it happens

`budget.max_cost_usd`, `max_calls` and `max_tokens` are checked *before* each
call. Breaching one stops the run cleanly, saves state, and leaves it
resumable — counters restored on resume, so a ceiling spans the whole novel
rather than resetting each time.

## ACC-10 — Structure, numbers and prompts live outside the Python

No stage order, no gate threshold and no prompt appears in the package source.
`tools/check_specs.py` fails if a stage names an agent with no skill, if a
skill contradicts its spec, or if a declared requirement has no test citing it;
`tests/test_agents.py` fails if a stage module contains a prompt.

## ACC-11 — What is not claimed

Stated so that the criteria above are not read as covering more than they do:

- `--engine anthropic` is not implemented. Every criterion here is verified
  against the mock engine only.
- The two critics are scored in code rather than by a model, which is what
  makes ACC-6 possible. Their skills declare `shipping: false`.
- The manuscript in `dist/` is not redacted. SEC-1 refuses a premise carrying a
  credential instead, because scrubbing an author's prose is its own
  corruption.

---

## Where these are checked

| Criterion | Covered by |
| --- | --- |
| ACC-1 | `tests/test_pipeline.py::TestItRuns` |
| ACC-2 | `tests/test_pipeline.py::TestTheGate` |
| ACC-3 | `tests/test_pipeline.py::TestTheGate` |
| ACC-4 | `tests/test_context.py`, `tests/test_agents.py::TestChapterWriter` |
| ACC-5 | `tests/test_critics.py::TestLengthCritic` |
| ACC-6 | `tests/test_golden.py`, `tests/test_engine_mock.py::TestDeterminism` |
| ACC-7 | `tests/test_resume.py` |
| ACC-8 | `tests/security/test_sec6_audit.py` |
| ACC-9 | `tests/security/test_sec6_audit.py::TestBudgetGuard` |
| ACC-10 | `tests/test_agents.py::TestPromptLoading` |

`tools/check_specs.py` fails if any identifier above has no test citing it.
