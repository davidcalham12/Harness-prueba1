# output/golden-tiny — the committed run

One complete run of the tiny profile, committed so a reader can see what the
harness produces without running anything: the Story Bible, the outline, every
chapter draft, **the failing first draft of chapter 2 and the verdict that
rejected it**, the audit log, and `dist/book.md`.

## What this is not

**The prose here has nothing to do with the premise on the command line.** The
mock engine ignores it. Run the same command with "a medieval blacksmith
discovers her forge can reforge memories" and `bible/characters.md`,
`outline.md` and every chapter come out byte-identical to what is in this
directory. Only `bible/world.md` and `synopsis.md` differ, because they quote
the premise verbatim in one line each.

That is what makes this directory a fixture: a run that reproduces byte for
byte cannot also respond to its input.

So read what follows as **evidence that the pipeline works** — the gate
rejecting a draft, the length band holding, the audit chain intact — and not
as a sample of what the harness would write for you. That sample does not
exist yet; `--engine anthropic` is not implemented.

## How it was generated

```bash
python -m novaforge new "A deep-space salvage crew finds a derelict that remembers them" --slug golden-tiny --profile tiny --engine mock
```

`--slug golden-tiny` is what puts it here; without it the slug is derived from
the premise. `--profile tiny` keeps it to three short chapters, and
`--engine mock` makes it deterministic and free, so this run is reproducible by
anyone who clones the repository.

Regenerating over an existing run needs `--force`, because `logs/agents.jsonl`
is append-only and a second run into an occupied slug would otherwise produce a
log describing two runs as though they were one.

## Start with chapter 2

`critiques/ch02.continuity.json` is the file worth opening first:

- `iterations[0]` scored 6/10 with a `name-drift` finding quoting `"Kassar"`,
  a one-character corruption of the canonical `Kassab` fixed in
  `bible/characters.md`;
- the gate rejected that draft and handed the finding back to the writer;
- `iterations[1]` — and `final` — scored 10/10 with no findings.

`chapters/ch02.md` is the accepted draft. The rejected one is not kept as prose;
the critique is the evidence, because it is what the gate actually acted on.

The drift is deliberate, injected by the mock engine into the first draft of
every even-numbered chapter (`engine.inject_drift`). A run where every chapter
passed first time would demonstrate nothing about the gate.

## What it is for

Two things, and the second is the important one:

1. A reader can judge the output without installing anything.
2. It is a fixture. When the mock engine, the wrapper or an exporter changes,
   regenerating this directory and diffing it shows exactly what moved. That is
   worth more than any assertion, because it catches the changes nobody thought
   to write a test for.

`tests/test_golden.py` enforces both: that this directory is complete and
internally consistent, and that a fresh run reproduces every artefact byte for
byte.

### The fields that legitimately differ

Every file here reproduces exactly — `dist/book.pdf` included, byte for byte —
**except** four fields in `logs/agents.jsonl`: `ts` (when a call happened) and
`elapsed_s` (how long it took), plus the `hash` and `prev` that chain each row
to the one before it.

That is one reason, not two. The chain hash covers the whole row including
`ts`, so a varying timestamp means a varying hash. Excluding `ts` from the hash
would make the timestamp the single field an edit could change undetected,
which is the opposite of what the chain is for.

Diff the log with those filtered:

```bash
python -c "import json,sys;[print(json.dumps({k:v for k,v in json.loads(l).items() if k not in ('ts','elapsed_s','hash','prev')},sort_keys=True)) for l in open(sys.argv[1],encoding='utf-8')]" logs/agents.jsonl
```

A fifth varying field would be a bug, and `test_only_the_wall_clock_fields_differ`
fails if one appears.

### Checking the chain yourself

```bash
python -c "from novaforge.security.audit import AuditChain; from novaforge.security.sandbox import Workspace; print(AuditChain(Workspace('output/golden-tiny', create=False)).verify())"
```

Expected: `chain intact (31 rows, hash chain)`. Edit any row in
`logs/agents.jsonl` and it names the row. This chain is unkeyed, so it is
tamper-evident only — anyone who rewrites the whole file can recompute it. Set
`NOVAFORGE_AUDIT_KEY` and it becomes an HMAC chain.

## Regenerating deliberately

Because it is a fixture, regenerate it deliberately and commit the diff as its
own change record rather than sweeping it into an unrelated commit.

## The PDF

`dist/book.pdf` is seven A5 pages of 10pt Helvetica, written by
`novaforge/export/pdf.py` with no dependency: a base-14 font needs no
embedding, so the whole book is a little over 7KB.

It does not match `dist/book.md` line for line, and should not. Markdown wraps
at a character count because a terminal and a diff are monospaced; the PDF
breaks lines against real Helvetica widths because a page is not.
