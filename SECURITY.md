# Security model

On `main`, this document described six layers, each one module under
`novaforge/security/` with a matching test module, and every `SEC-n.m`
identifier was cited from the docstring of a test that covered it.

**This branch has no security layers of its own.** The package that held them is
deleted. What is left is what Claude Code provides, what the subagents' tool
lists happen to guarantee, and a list of the risks now nobody is handling.

This document keeps the `SEC-n` numbering so the two branches can be compared
line by line, and says for each layer where it went.

## Threat model

Unchanged, because deleting the mitigations did not delete the risks:

1. **Untrusted text becoming instructions.** Every agent's output is another
   agent's input. Model output is data, including when it is re-read from the
   Story Bible three stages later.
2. **Model-derived values reaching the filesystem.** Chapter filenames, slugs
   and artefact names all originate outside the program.
3. **Credentials leaking into artefacts.** Logs and terminal output get copied
   into tickets and chat messages.
4. **Unbounded spend.** A rewrite loop against a paid API is a loop that can
   bill.
5. **An unreconstructable run.** If you cannot show afterwards what the agents
   actually did, you cannot review the result.

---

## SEC-1 — Input validation → **gone**

`main` refuses a slug that is not `^[a-z0-9][a-z0-9-]{0,63}$` or is a Windows
device name, bounds the premise's length, and refuses a premise containing
control or invisible-format characters (Unicode `Cc`/`Cf`) — the class that hides
text from a human reviewer while the model still reads it. It also refuses a
premise carrying something credential-shaped.

Here nothing validates either. The slug is a name the orchestrator derives and
should sanity-check by eye before creating a directory from it.

**The credential rule is worth keeping by hand.** A premise reaches the Story
Bible verbatim and from there the manuscript, and nothing downstream scrubs
prose. A secret pasted into a premise ends up in the book. On `main` the door was
the only place that could be caught; here there is no door.

## SEC-2 — Secrets → **inherited, and narrower**

This branch handles no API key. Claude Code holds the credential and the
orchestrator never sees one, which removes the leak path rather than mitigating
it — the strongest form of the guarantee, and the one thing security-wise that
got better.

What is gone is the `Redactor`: nothing scrubs key-shaped strings, bearer tokens
or `api_key=` assignments out of `logs/agents.jsonl` or out of what is printed.
If a secret enters the conversation it stays in the transcript.

`main`'s rule still applies to anything added here: **credentials come from the
environment, never from a flag**, because a flag lands in shell history and in the
process table.

## SEC-3 — Filesystem sandbox → **inherited from Claude Code**

`main` routes every read and write through a `Workspace` bounded by
`output/<slug>/`, checks containment after `realpath` so a planted symlink is
caught, and writes atomically via `os.replace` so a crash cannot leave a
half-written Bible.

Here the bound is Claude Code's own permission model, and it is a different kind
of bound: it asks a person rather than enforcing a prefix. Writes are not atomic.
An interrupted run can leave a partial file, and the orchestrator should re-read
anything it was mid-write on rather than trusting it.

Two subagents can write at all — `worldbuilder` and `character-architect` — and
their prompts name the files. Nothing stops them writing elsewhere in the
workspace.

## SEC-4 — Prompt-injection defence → **partly structural, mostly gone**

`main` has three mechanisms. Their fate here differs, and the difference is the
most interesting thing in this document.

**Framing — gone.** Non-operator content was wrapped in labelled `<untrusted>`
blocks with nested delimiters escaped so the block could not be closed from
inside. Nothing wraps anything here. When the orchestrator quotes `bible/world.md`
into a critic's prompt, it is quoting model-written text as plain text.

**The standing clause — gone as a mechanism**, though every agent file could
carry it. It is not currently written into them.

**Authority — stronger than it was.** On `main`, only `worldbuilder` and
`character_architect` could write the Story Bible, enforced by a code check keyed
on the role the orchestrator invoked. Here those same two agents are the only
ones with the `Write` tool at all; the other six have `Glob`, which returns paths
and cannot return or modify anything. An agent that is told to write canon cannot
comply, whatever a prompt persuades it of.

The same mechanism carries the context policy. `chapter-writer` has `Glob` alone,
so a prior chapter's prose is unreachable to it — the claim the whole project is
built on, held by a capability rather than by an assertion. See ACC-4.

**Not covered, on either branch:** a determined injection the model obeys anyway.
Capability limits are what remain when framing fails, which is why the two that
survived here are the two worth having.

## SEC-5 — Output sanitisation → **gone, and one failure mode returns**

`main` escapes model-written text for each format's structural syntax:
`markdown_prose` neutralises structure at the start of a prose line, `pdf_string`
escapes `\ ( )` and octal-encodes non-ASCII, and control characters are stripped
from every artefact.

The PDF half is moot — there is no PDF here. The Markdown half is not. **A
paragraph that happens to begin `## ` becomes a chapter heading in
`dist/book.md`**, and the structure of the assembled book is then wrong in a way
nobody notices until it is read. Concatenation does not fix that; only escaping
does, and nothing escapes.

## SEC-6 — Audit and spend limits → **gone, both halves**

`main` checks `budget.max_cost_usd`, `max_calls` and `max_tokens` *before* each
call, raises `BudgetExceeded`, saves state and leaves the run resumable, with
counters restored on resume so a ceiling spans the whole novel.

Nothing here checks anything before a call. The `budget` block in the config is
advisory. The orchestrator states the implied call count in its plan and a person
decides — which is a control, but a control that runs once at the start rather
than before every call.

`main`'s `logs/agents.jsonl` is append-only with each row carrying the SHA-256 of
the row before it, so `verify()` detects any row edited, removed, inserted or
reordered — tamper-**evident**, never tamper-**proof**, and an HMAC chain with
`NOVAFORGE_AUDIT_KEY` set.

The log here is a flat JSONL file the orchestrator appends to. It is not chained
and nothing verifies it. Calling it an audit log would be a category error; it is
a record of what happened, trusted to the extent you trust the process that wrote
it.

---

## Summary

| Layer | `main` | this branch |
| --- | --- | --- |
| SEC-1 input validation | enforced, tested | none |
| SEC-2 secrets | redactor, env-only key | no key handled at all; no redactor |
| SEC-3 filesystem | `realpath`-bounded, atomic | Claude Code permissions; not atomic |
| SEC-4 injection | framing + clause + code guard | tool lists only — but those are stronger |
| SEC-5 output escaping | enforced, tested | none |
| SEC-6 audit + budget | hash chain, pre-call ceilings | flat log, advisory numbers |

One row improved and five got worse. If that trade is not the one you want, the
`main` branch is the same project with all six.

## Reporting

This is a sample project, not a deployed service. A fix to anything above
belongs on `main`, where there is a module to put it in and a test to pin it.
