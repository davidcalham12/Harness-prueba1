# CONFIG-SPEC — the configuration layer

What `config/novel.config.json` and `config/profiles/*.json` are for, and the
rules the loader in `novaforge/config.py` enforces.

**On the numbering.** The identifiers below have gaps. They are the ones
already cited from the code and the documentation — `CFG-1` in
`novaforge/config.py`, `CFG-4` in `novaforge/cli.py`, `CFG-5.1` in
`novaforge/context.py`, `CFG-6` in every profile's `_comment`, `CFG-10.7` in
`RUNBOOK.md`. Renumbering them to be tidy would invalidate every one of those
citations, which is a worse outcome than a spec that counts unevenly.

---

## CFG-1 — The base config is complete and authoritative

`config/novel.config.json` holds a value for **every** setting the program
reads. Profiles and flags overlay it; nothing overlays *into* it.

This is what lets the loader raise on a missing key instead of guessing. A base
config with holes would make "the key is absent" ambiguous between "you made a
typo" and "this one has no default", and the loader would have to tolerate
both.

## CFG-2 — Four layers, in one order

    config/novel.config.json     the complete default
    config/profiles/<name>.json  a partial, from --profile
    <path>                       a partial, from --config
    CLI flags                    the narrowest, one key at a time

Later layers win. `config.snapshot.json` records which layers a run used, so a
resolved value can be traced back to the file it came from.

Passing the packaged base to `--config` is a no-op: the loader recognises it by
`samefile` and skips it. Re-merging it would be worse than pointless — layered
on top of a profile it would restore the base's values and silently undo the
profile, so `--profile tiny --config config/novel.config.json` would quietly be
twelve chapters.

## CFG-3 — Dicts merge, lists replace

The merge is recursive: a profile that sets `outputs.pdf.page_size` keeps the
base's `outputs.pdf.margins_mm`. That is the difference between an overlay and
a replacement, and getting it wrong is how a profile silently ships a PDF with
no margins.

Lists replace wholesale, on purpose. A profile setting `outputs.formats` to
`["markdown"]` means *only* markdown, not markdown appended to what was there.

## CFG-4 — Every CLI flag is a config key

`--chapters 3` and editing `novel.chapters` in JSON are the same change
arriving by different routes. A flag that had no config key behind it would be
a setting you could not record in a profile or recover from a snapshot.

Only flags the caller actually passed become an overlay. An absent flag
inherits from the profile rather than overwriting it with an `argparse`
default — which is why the flags default to `None` rather than to a value.

## CFG-5 — No config value is duplicated as a Python literal

If the loader carried its own fallback for, say, `max_summary_words`, there
would be two answers to the question and the JSON would only sometimes be the
real one.

### CFG-5.1 — A missing key raises

`Config.get` raises `ConfigError` unless the caller passes an explicit default.
A typo in a key name becomes an error at the first read instead of a silently
wrong novel.

The one sanctioned exception is a module-level constant used by callers that
have no config at all — `novaforge/context.py`'s `LEAK_WINDOW` is the only one,
and it is documented as a fallback for callers outside a run.

## CFG-6 — A profile is partial

It states what it changes and nothing else. `tiny`, `small`, `medium` and
`full` each declare `novel`, `context` and `budget`; only `tiny` also declares
`outputs`, because it is the only one that changes the page size.

Each carries a `_comment` saying what it is for. `_comment` keys are stripped
before hashing, so documenting a profile does not invalidate every audit row
that cites the old hash.

## CFG-7 — The golden fixture is regenerated deliberately

`output/golden-tiny/` is committed, and a change to the config changes it.
Regenerate it as its own change record rather than sweeping it into an
unrelated commit, because its value is that a diff shows exactly what moved.

Regenerating over an existing run requires `--force`, since `logs/agents.jsonl`
is append-only and a second run into an occupied slug would otherwise produce a
log describing two runs as though they were one.

## CFG-8 — The config hash identifies a run

A 12-hex-digit SHA-256 of the resolved config as canonical JSON — sorted keys,
no whitespace, `_comment` stripped. The same settings hash the same on any
machine.

Every audit row carries it, `state.json` records it, and `resume` refuses if it
does not match. That is what makes "these two runs differed only in the config"
a checkable statement rather than a claim.

## CFG-9 — The config owns numbers; the spec owns structure

`specs/flow.yaml` decides which stages exist, their order, their `impl` and
which may write the Story Bible. The config decides which critics are in the
gate, what score clears it, how many drafts are allowed, how long a chapter is.

`novaforge/spec/flow.py:apply_config` is where the second overwrites the first,
and every value it moves is recorded in `FlowSpec.substitutions` and logged as
a `spec_substitution` row. The spec on disk is therefore not always exactly
what ran, and the log says so.

The config may make a gate harder or easier. It may **not** add a gate to a
stage the spec did not gate — that is a structural change being made from the
wrong file.

## CFG-10 — The same code writes a different novel

### CFG-10.7 — A profile change alone

```bash
python -m novaforge new "<premise>" --profile tiny  --engine mock
python -m novaforge new "<premise>" --profile small --engine mock
```

Three chapters of 300–550 words, then eight of 900–1400. **No Python is edited
between the two runs**, and no argument other than the profile changes.

That is the point of the whole config layer. If a length, a threshold or a
budget could only be changed by editing a module, then every one of those
numbers would be a code review instead of a setting.

---

## Where these are checked

`tests/test_config.py` covers the loader; `tests/test_spec.py` covers
`apply_config`; `tests/test_pipeline.py` covers the run-level consequences.
`tools/check_specs.py` fails if any identifier above has no test citing it.
