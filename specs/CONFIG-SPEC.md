# CONFIG-SPEC — the configuration layer

What `config/novel.config.json` and `config/profiles/*.json` are for, and the
rules the orchestrator follows when it merges them.

**On the numbering.** The identifiers below have gaps, and two are withdrawn.
They were assigned when a Python loader enforced them and they are cited from
other documents, so renumbering them to be tidy would invalidate those citations
— a worse outcome than a spec that counts unevenly. A withdrawn identifier keeps
its number and says what it used to mean.

**On enforcement.** On `main`, `novaforge/config.py` enforced these rules and
`tests/test_config.py` checked that it did. Here the orchestrator follows them
because `SKILL.md` says to. Every rule below is therefore a rule a procedure
observes, not one a loader imposes. Where that difference has teeth, it is
marked.

---

## CFG-1 — The base config is complete and authoritative

`config/novel.config.json` holds a value for **every** setting the pipeline
reads. Profiles overlay it; nothing overlays *into* it.

On `main` this is what let the loader raise on a missing key instead of
guessing. Here nothing raises — an absent key is simply a value the orchestrator
will not find, and what happens next depends on it noticing. Keeping the base
complete is therefore more important here, not less.

## CFG-2 — Two layers, in one order

    config/novel.config.json     the complete default
    config/profiles/<name>.json  a partial, from the profile

Later layers win. The merged result is written to
`output/<slug>/config.snapshot.json`, so a resolved value in a finished run can
be traced back.

The third and fourth layers on `main` — an arbitrary `--config` file and
individual CLI flags — do not exist here, because there is no CLI. A one-off
change is made by saying so in the request, and the snapshot is what records it.

## CFG-3 — Dicts merge, lists replace

The merge is recursive: a profile that sets `novel.chapters` keeps the base's
`novel.tone`. That is the difference between an overlay and a replacement.

Lists replace wholesale, on purpose. A profile setting `outputs.formats` to
`["markdown"]` means *only* markdown, not markdown appended to what was there.

**This one is easy to get wrong by hand**, which is exactly what the orchestrator
now does. Merge key by key; do not replace a whole section because the profile
mentioned it.

## CFG-4 — Withdrawn: every CLI flag is a config key

There is no CLI on this branch. The rule existed so that `--chapters 3` and
editing `novel.chapters` were the same change arriving by different routes, and
so that a setting could not exist that a profile could not record.

The spirit survives as: **anything worth changing twice belongs in a profile**,
not in the sentence you typed at the orchestrator.

## CFG-5 — No config value is duplicated elsewhere

If `SKILL.md` carried its own fallback for, say, `max_summary_words`, there would
be two answers to the question and the JSON would only sometimes be the real one.

Read `SKILL.md` with this in mind: it names keys, it does not quote values. The
one number it states is a shape (`ch0N`), not a setting.

### CFG-5.1 — A missing key is an error, not a default

If a key the procedure needs is absent, stop and say so. Do not substitute a
plausible number. A silently wrong novel is worse than a run that halts, and on
this branch nothing else will catch it.

## CFG-6 — A profile is partial

It states what it changes and nothing else. `tiny`, `small`, `medium` and `full`
each declare `novel`, `context` and `budget` and nothing more.

Each carries a `_comment` saying what it is for. `_comment` keys are stripped
before hashing, so documenting a profile does not change the config hash.

## CFG-7 — Withdrawn: the golden fixture is regenerated deliberately

`output/golden-tiny/` was a committed run whose byte-for-byte diff showed exactly
what a config change moved. It is deleted on this branch, because nothing here
reproduces. It still exists on `main`.

This is the rule whose loss costs the most. The fixture was not a test of output
quality — it was the mechanism that caught changes nobody thought to write a test
for.

## CFG-8 — The config hash identifies a run

A 12-hex-digit SHA-256 of the resolved config as canonical JSON — sorted keys, no
whitespace, `_comment` stripped. The same settings hash the same on any machine.

The orchestrator computes it once and writes it into `config.snapshot.json`,
`state.json` and every row of `logs/agents.jsonl`. Its job is unchanged: to make
"these two runs differed only in the config" a checkable statement.

What is gone is the check that used it — `resume` refused to continue a run whose
config hash had moved. Nothing refuses now.

## CFG-9 — The config owns numbers; the spec owns structure

`specs/flow.yaml` decides which stages exist, their order, which agent runs each
one and which may write the Story Bible. The config decides which critics are in
the gate, what score clears it, how many drafts are allowed, how long a chapter
is.

The config may make a gate harder or easier. It may **not** add a gate to a stage
the spec did not gate — that is a structural change being made from the wrong
file.

Where the two disagree on a shared value, the config wins and the orchestrator
should say so in its report, the way `apply_config` used to log a
`spec_substitution` row. The spec on disk is not always exactly what ran.

## CFG-10 — The same procedure writes a different novel

### CFG-10.7 — A profile change alone

Run the skill twice with the same premise, once with `tiny` and once with
`small`: three chapters of 300–550 words, then eight of 900–1400. **No prompt and
no procedure is edited between the two runs**, and nothing changes but the
profile name.

That is the point of the whole config layer. If a length, a threshold or a budget
could only be changed by editing an agent's prompt, then every one of those
numbers would be a review instead of a setting.

## CFG-11 — Withdrawn: observability is additive, and off by default

`observability.sink` selected where a run was *also* reported, and `main` sends
one trace per run, one generation per call and one score per verdict to Langfuse,
with a `GuardedSink` making "a sink may never fail a run" a property of being a
sink rather than something each implementation remembered.

None of that is on this branch. There is no sink, no trace, no score and no
prompt management. What a run did is in the Claude Code transcript and in
`logs/agents.jsonl`, and neither was designed for the job.

The three rules it laid down are still the right rules, and are the thing to
bring back first if observability returns: **it may add, never replace; it may
never change a run; what leaves the machine is scrubbed.**

## CFG-12 — Withdrawn: prompts are managed in Langfuse

`agents.prompt_source` was `"langfuse"`, with the `SKILL.md` files as the
fallback that `get_prompt` takes as an argument. Editing a prompt in the
dashboard changed the next run, with a version history and a label.

Here the prompt *is* the file — `.claude/agents/<name>.md` — and changing it is a
commit. That is a real regression in how fast a prompt can be tuned, and a real
improvement in the prompt being reviewable next to the spec it implements.

**One rule from CFG-12 survives and matters more now.** Authority is never read
from a prompt source: whether an agent may write the Story Bible is decided by
`specs/flow.yaml` and, on this branch, by the agent's tool list. A prompt supplies
wording and nothing else.

---

## Where these are checked

Nowhere automatically. On `main`, `tests/test_config.py` covered the loader,
`tests/test_spec.py` covered `apply_config`, and `tools/check_specs.py` failed if
any identifier above had no test citing it.

Here a reader is the check. The most useful thing to read is
`output/<slug>/config.snapshot.json` after a run: if a number in it surprises
you, the merge went wrong.
