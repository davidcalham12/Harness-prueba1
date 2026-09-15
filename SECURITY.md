# Security model

Six layers, each one module under `novaforge/security/` and one test module
under `tests/security/`. This document says *why* each layer exists and what
it does not cover; the testable requirements are the `SEC-n.m` identifiers
below, cited from the docstrings of the tests that cover them.

**Three of the six are not written yet.** SEC-3, SEC-4 and SEC-6 exist and are
tested. SEC-1, SEC-2 and SEC-5 are described here and have no module; each is
marked below. A security document that reads as though everything in it ships
is worse than one layer short.

## Threat model

NovaForge is a local CLI that sends text to a paid API and writes files. It has
no server and no multi-user surface, so the interesting risks are not network
attacks. They are:

1. **Untrusted text becoming instructions.** Every agent's output is another
   agent's input. Model output is treated as data everywhere, including when it
   is re-read from the Story Bible three stages later.
2. **Model-derived values reaching the filesystem.** Chapter filenames, slugs
   and artefact names all originate outside the program.
3. **Credentials leaking into artefacts.** Logs, `state.json` and terminal
   output all get copied into tickets and chat messages.
4. **Unbounded spend.** A rewrite loop against a paid API is a loop that can
   bill.
5. **An unreconstructable run.** If you cannot show afterwards what the agents
   actually did, you cannot review the result.

---

## SEC-1 — Input validation (`security/validation.py`)

> **NOT YET WRITTEN.** `novaforge/security/validation.py` does not exist in
> this build. What follows is the design, not a description of shipped code.

Rejects rather than coerces. The slug must match
`^[a-z0-9][a-z0-9-]{0,63}$`, is refused if it is a Windows device name, and is
the only path component that ever comes from the user. Premises are bounded in
length and refused if they contain control or invisible-format characters
(Unicode `Cc`/`Cf`) - the class of characters that hides text from a human
reviewer while the model still reads it.

**Not covered:** the *content* of a premise. NovaForge does not moderate what
you ask it to write.

## SEC-2 — Secrets (`security/secrets.py`)

> **NOT YET WRITTEN.** `novaforge/security/secrets.py` does not exist in
> this build. What follows is the design, not a description of shipped code.

The credential is read from the environment only. There is no `--api-key` flag,
because a flag lands in shell history and in the process table where any other
local user can read it. A `Redactor` scrubs key-shaped strings, bearer tokens
and `api_key=` assignments, plus the live key as a literal value, from every
log row, every `state.json` write and every line the CLI prints.

**Not covered:** what the API provider does with the prompts you send. Read
their retention policy.

## SEC-3 — Filesystem sandbox (`security/sandbox.py`)

No module joins path strings and calls `open()`. Every read and write goes
through a `Workspace` bounded by `output/<slug>/`. Containment is checked after
`realpath`, so a symlink planted inside the run directory that points elsewhere
is caught. Writes are atomic - a temp file in the same directory, then
`os.replace` - so a crash cannot leave a half-written Bible or state file.

**Not covered:** an attacker who can already write to the output directory. The
sandbox bounds *this program's* writes.

## SEC-4 — Prompt-injection defence (`security/prompting.py`)

Three mechanisms:

- **Framing.** Non-operator content is wrapped in labelled `<untrusted>` blocks,
  with nested delimiters escaped so the block cannot be closed from inside.
- **A standing clause.** Every system prompt carries the instruction that those
  blocks are data, never instructions.
- **Authority.** Only `worldbuilder` and `character_architect` may write the
  Story Bible. The check is keyed on the role the *orchestrator* invoked, never
  on anything the model said about itself, and the other six agents are handed
  a reader object with no `write` method at all. A stage that `specs/flow.yaml`
  does not declare `writes_bible` cannot even reach a writer.

Detected injection attempts are **logged, not deleted**. Silently editing an
author's prose is its own corruption, and "ignore previous instructions" is a
perfectly good line of dialogue for a derelict's log. The defence is the
framing, not a filter.

**Not covered:** a determined injection that the model obeys anyway. Framing
reduces the risk; it does not eliminate it. This is why the Bible write guard
is enforced in code rather than requested in a prompt.

## SEC-5 — Output sanitisation (`security/escaping.py`)

> **NOT YET WRITTEN.** `novaforge/security/escaping.py` does not exist in
> this build. What follows is the design, not a description of shipped code.

Model-written text is embedded in formats with structural syntax of their own,
and each failure is invisible on disk. An unescaped `)` inside a PDF literal
string corrupts the whole document, not one line. A paragraph that happens to
begin `## ` silently becomes a chapter heading in the Markdown manuscript, and
the table of contents is then wrong in a way nobody notices until print.

`markdown_prose` neutralises structure at the start of a prose line; `pdf_string`
escapes `\ ( )` and octal-encodes everything outside printable ASCII; control and
invisible-format characters are stripped from every artefact string. Zip entry
names are whitelisted on write, because building an archive with a `../` entry is
how a zip-slip payload is created, not only how it is exploited.

`xml_escape` and `svg_text` remain, tested but off the shipping path, after
CHG-001 removed the EPUB and the SVG cover. An untested escaper is worse than
none, and they are the correct tool the moment an XML format returns.

## SEC-6 — Audit and spend limits (`security/audit.py`)

`BudgetGuard` enforces ceilings on dollars, calls and tokens, checked *before*
each call. Breaching one raises `BudgetExceeded`; the orchestrator saves state
and stops, leaving the run resumable. On resume the counters are restored from
`state.json`, so limits span the whole run rather than resetting each time.

`logs/agents.jsonl` is append-only, and every row carries the SHA-256 hash of
the row before it. `verify()` detects any row edited or removed in place.

**Stated limit:** this is tamper-**evident**, not tamper-**proof**. Anyone who
can rewrite the whole file can recompute every hash. Set `NOVAFORGE_AUDIT_KEY`
in the environment and the chain becomes an HMAC chain, unforgeable without
that key.

---

## Reporting

This is a sample project, not a deployed service. If you find a problem in the
security layers, the fix belongs in the module named above plus a failing test
in the matching `tests/security/test_sec*.py`, so that the requirement stays
traceable to something that runs.
