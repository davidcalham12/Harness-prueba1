# CHG-002 — The acceptance criteria were unverified

**Status:** closed. Every criterion in `specs/acceptance.md` now passes.

## What this recorded

The session that assembled this repository had no working shell. Every shell
invocation failed, `echo hello` included. So the project was written but never
run: no test had executed, no command in `RUNBOOK.md` had been tried, and
`output/golden-tiny/` was an empty directory with a README explaining why.

This record existed to say so item by item, rather than letting a reader assume
that documentation this confident described something that worked.

## Why it was recorded rather than hidden

The alternative was to write plausible-looking output by hand. A fabricated
golden run is a lie that every later comparison inherits — the first real
regeneration would produce a large diff, and nobody would know which side was
right.

The same reasoning applied to `RUNBOOK.md`, whose first line admitted that none
of its commands had been executed, and whose § 3 quoted an *imagined* expected
output.

## How it closed

The project was built out and run. In order:

1. The missing ~90% of the implementation was written — the CLI, the
   orchestrator, the spec loader, the engines, the critics, the stages and the
   exporters.
2. `tests/` was written and the suite executed.
3. `output/golden-tiny/` was generated, and `tests/test_golden.py` now asserts
   that a fresh run reproduces it byte for byte.
4. `RUNBOOK.md` § 3's expected output was replaced with a transcript of a real
   run, including its actual config hash and totals.

## What is still unverified, and named as such

`--engine anthropic` is not implemented. Every acceptance criterion is verified
against the mock engine only, and `specs/acceptance.md` § ACC-11 says so.

This record stays in the repository rather than being deleted. A change record
that vanishes once it is resolved takes with it the reason anyone should
believe the current state.
