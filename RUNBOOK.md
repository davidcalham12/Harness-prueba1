# Runbook — what to run, and what to expect

**The commands below have been executed and pass.** That was not true when this
file was first written — the session that assembled the repository had no
working shell, so every step here was a prediction. They have since been run on
Python 3.12 on Windows, and the expected output quoted below is transcribed from
a real run rather than imagined.

The criteria these commands check are in `specs/acceptance.md`, and
`specs/changes/CHG-002-acceptance-unverified.md` records how they went from
predicted to verified. What still does not exist is called out where it
appears, and the README's "What is not done yet" section lists it in one
place.

## 0a. Publishing

The repository is <https://github.com/davidcalham12/Harness-prueba1>. Nothing has
been pushed to it yet.

One command does the whole handover. It runs the checks below **first**, plus a
regeneration of `output/golden-tiny/`, and refuses to push if any of them fail:

```powershell
.\tools\publish.ps1 -Message "what changed"
```

`-Force` pushes despite failures and annotates the commit message to say which
ones were failing. `-SkipGolden` skips the fixture check, `-NoPush` stops after
the commit. There is no remote configured yet, so the first run will commit
locally and tell you how to add one.

## 0. Which command to run

```bash
python -m novaforge new "A deep-space salvage crew finds a derelict that remembers them" --config config/novel.config.json
```

This runs the **base** configuration: twelve chapters of 800-1300 words. Passing
the packaged config to `--config` is a no-op overlay — it is already the bottom
layer — so the command is equivalent to passing nothing, and it is a slow first
run to read.

For a first look, use the tiny profile instead (§ 3). For the committed fixture,
use `--slug golden-tiny --profile tiny` (§ 4b).

## 1. The test suite

```bash
python -m pytest -q
```

Expected: everything passes, offline, in a few seconds. Tests marked `live` are
skipped unless `ANTHROPIC_API_KEY` is set.

## 2. The spec checker

```bash
python tools/check_specs.py -v
```

Expected: `specs OK: 8 agent specs, 8 skills, 16 requirements, all traced`,
plus a note naming the two critic skills that are declared off the shipping
path — this build scores continuity and science in code so that a mock run
stays reproducible.

It fails if `specs/flow.yaml` names an agent with no spec or no `SKILL.md`, if
any spec identifier has no test docstring referencing it, or if a `SKILL.md`
front matter contradicts its agent spec on role, model or `writes_bible`.

## 3. The demo run

```bash
python -m novaforge new "A deep-space salvage crew finds a derelict that remembers them" --profile tiny --engine mock
```

Expected output, transcribed from a real run — the config hash and the
totals below are the actual ones:

```
NovaForge: A deep-space salvage crew finds a derelict that remembers th  [hard-scifi, 3 chapters]
  profile tiny     config 58b26878bd29
  spec    .../specs/flow.yaml
  engine  mock / claude-opus-5
  length  300-550 words per chapter, wrapped at 64
  gate    continuity+science+length >= 8, 2 rewrites allowed, on_fail=accept_with_warnings
  budget  $5.00, 120 calls, 1,000,000 tokens
  output  ...\output\a-deep-space-salvage-crew-finds-a-derelict-that

  [1/6] FLOW-1 worldbuild -> worldbuilder
    wrote bible/world.md (234 words, 4 rules)
  [2/6] FLOW-2 characters -> character_architect
    wrote bible/characters.md (45 words, 4 characters)
    wrote bible/timeline.md (94 words)
    wrote bible/mysteries.md (63 words)
  [3/6] FLOW-3 outline -> plot_architect
    wrote outline.md (3 chapters, tension 3, 6, 9)
  [4/6] FLOW-4 chapters -> chapter_writer
    gate continuity+science+length >= 8, max 3 drafts, on_fail=accept_with_warnings
    ch01 draft 1: continuity 10/10, length 10/10, science 10/10 -> accept
    ch02 draft 1: continuity 6/10, length 10/10, science 10/10 -> retry
      [continuity] name-drift: 'Kassar'
    ch02 draft 2: continuity 10/10, length 10/10, science 10/10 -> accept
    ch03 draft 1: continuity 10/10, length 10/10, science 10/10 -> accept
    3/3 chapters approved, 0 accepted with warnings
  [5/6] FLOW-5 style -> style_editor
    wrote 3 final chapters, no content changed
  [6/6] FLOW-6 publish -> publisher
    wrote synopsis.md (183 words)
    wrote dist/book.md — 3 chapters, 1,284 words, wrapped at 64 columns
    wrote dist/book.pdf — 7 pages, A5, 10pt Helvetica, 6,861 bytes

  chapters  3 approved
  calls     16  (9,397 in / 5,616 out tokens)
  cost      $0.1874
  audit     chain intact (31 rows, hash chain)
  done. artefacts in ...\output\a-deep-space-salvage-crew-finds-a-derelict-that\dist
```

**The premise does not reach the prose.** The mock engine ignores it; the same
chapters come out whatever you type. What this run demonstrates is the
pipeline, not the writing. See `novaforge/engines/mock.py` for why, and
`specs/acceptance.md` § ACC-11 for what that means the criteria do not cover.

Two lines matter most. `ch02 draft 1 ... -> retry` is the critique loop firing.
`length 10/10` on every chapter is the Length Critic confirming that the prose
came out the size the config asked for - and if the mock ever drifts out of
band, that number turns into a `0` and the chapter is rewritten, which is
exactly what it is there for.

### 3b. The same code, a different novel

```bash
python -m novaforge new "A deep-space salvage crew finds a derelict that remembers them" --profile small --slug salvage-small --engine mock
```

Eight chapters of 900-1400 words. **No Python was edited between the two runs.**
That is CFG-10.7, and it is the point of the whole config layer.

A run where every chapter passes first time would prove nothing about the gate,
which is why the mock deliberately drifts a character's surname in the first
draft of even-numbered chapters. It is controlled by `engine.inject_drift`,
documented in `.claude/skills/continuity_critic/SKILL.md`, and covered by
`tests/test_engine_mock.py::TestDrift`.

## 4b. Generate the committed fixture

```bash
python -m novaforge new "A deep-space salvage crew finds a derelict that remembers them" --slug golden-tiny --profile tiny --engine mock
```

`output/golden-tiny/` is committed so a reader can see the output without
running anything, and so that a later change to the mock engine or an exporter
shows up as a diff. It is generated — see its README for what to look at first
and for the two fields that legitimately differ between regenerations.

Regenerating over it needs `--force`, because `logs/agents.jsonl` is
append-only and a second run into an occupied slug would otherwise produce a
log describing two runs as though they were one.

## 4. Inspect the evidence

```bash
python -m novaforge status a-deep-space-salvage-crew-finds-a-derelict-that
```

Then look at, in this order:

| File | What it should show |
| --- | --- |
| `output/<slug>/config.snapshot.json` | the resolved tiny profile, complete |
| `output/<slug>/critiques/ch02.continuity.json` | `iterations[0]` has a `name-drift` finding quoting the drifted surname; `final.findings` is empty |
| `output/<slug>/critiques/ch02.length.json` | words, lines and paragraphs, all in band |
| `output/<slug>/logs/agents.jsonl` | one row per call, each naming its `flow_id` **and `config_hash`**, plus `gate_decision` rows |
| `output/<slug>/logs/cost.json` | totals at $5/$25 per MTok |
| `output/<slug>/state.json` | every chapter `approved`, `stage: complete`, `config_hash` matching the snapshot |
| `output/<slug>/dist/` | exactly `book.md` and `book.pdf` |

## 5. Resume

```bash
python -m novaforge resume a-deep-space-salvage-crew-finds-a-derelict-that
```

On a completed run this reports every stage as already done and exits 0. To see
it actually resume, delete `chapters/ch03.md` and `chapters/ch03.final.md`, set
that chapter's `status` back to `pending` in `state.json`, remove `FLOW-4`,
`FLOW-5` and `FLOW-6` from `completed_stages`, and run it again: only chapter 3
is rewritten. `tests/test_resume.py` does exactly this automatically.

## 6. Against the real model

```bash
python -m novaforge new "your premise here" --profile tiny --engine anthropic --max-cost-usd 5
```

Requires `ANTHROPIC_API_KEY` in the environment (there is no `--api-key` flag).
Start with the tiny profile and a low `--max-cost-usd`: the ceiling is checked
before every call and stops the run cleanly, still resumable, rather than
discovering the bill afterwards.

## If something fails

The failure is most likely in one of three places, in order of likelihood:

1. **`novaforge/spec/miniyaml.py`** parsing `specs/flow.yaml` — the built-in
   parser covers a deliberate subset. `pip install pyyaml` makes `safe_load`
   defer to PyYAML instead, which is a useful way to bisect.
2. **`novaforge/engines/mock.py`** text generation feeding the deterministic
   critics — e.g. a generated sentence tripping a science rule, which would
   show up as a chapter that never clears the gate.
3. **`novaforge/export/pdf.py`** — the Helvetica metrics table is accurate to
   the last decimal for line breaking only; a wrong entry shifts a line break
   and nothing else.

Paste the failing output and it can be fixed directly.
