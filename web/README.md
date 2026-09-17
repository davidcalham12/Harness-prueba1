# web/ — the run panel

A read-only viewer for NovaForge runs. It reads the files the pipeline already
writes and turns them into four screens plus a replay.

```bash
cd web
npm install
npm run dev      # http://localhost:5178
npm test         # 28 checks against the committed run
npm run build    # a directory of static files in dist/
```

**Read-only means read-only.** The panel launches no run, calls no model, holds
no credential and writes nothing back. There is no backend: `vite.config.ts`
serves repository files at `/data/<path>` in development and copies them into
`dist/data/` at build time, so the built output is a folder of static files.

## Where every number comes from

| screen | reads |
| --- | --- |
| Quality | `logs/agents.jsonl`, `critiques/*.json` |
| Run | `logs/agents.jsonl`, `specs/flow.yaml`, `.claude/agents/*.md`, `config/pricing.json` |
| Configurator | `config/novel.config.json`, `config/profiles/*.json`, the measured run |
| Manuscript | `bible/*.md`, `outline.md`, `chapters/*.final.md`, `synopsis.md`, `dist/book.md` |

The six stages and the eight agents are **parsed, never transcribed**. Reorder a
stage in `specs/flow.yaml` or change an agent's tool list and the panel follows
without a TypeScript edit. That is the repository's own rule about those files
and the panel is not allowed a private copy of them.

## Three rules it will not break

**Every figure carries its provenance.** ● measured, ◐ reported by the agent,
◌ reconstructed after the fact, — not recorded. The distinction is not
decorative: the worldbuilder reported ~870 words when `wc -w` counted 948, so a
figure an agent supplied about itself is a different kind of fact from one the
orchestrator counted.

**Cost is always three figures.** The harness reports one token total per call
with no input/output split, so cost cannot be computed, only bounded. The two
bounds are exact arithmetic; the middle figure applies `assumed_input_share`
from `config/pricing.json`, which is a declared assumption. Rendering the
estimate alone would present a judgement as a measurement.

**Sources that disagree are shown disagreeing.** `state.json` says 25 subagent
calls and the log holds 24 rows with an `agent` field. The panel prints both and
names each source. Picking one silently would be the panel deciding which of its
own inputs to believe, which is the judgement a reader opened it to make.

## What it will not do

No backend, no button that starts a run, no API call, no key. The configurator
ends at a downloaded JSON and a command to copy, because the orchestrator is
Claude Code in a terminal and there is no headless entry point to call.

## Known gaps, marked in the interface rather than hidden

- **Duration is not recorded.** Several log rows share a timestamp because it is
  written per group, not per call. Order is real; spacing is not. Nothing is
  drawn proportional to time.
- **Rejected drafts are not on disk.** Only the accepted text survives, so there
  is no diff to show. The critique is the evidence, because it is what the gate
  acted on.
- **The flat-context chart is a proxy.** It plots tokens consumed, not the size
  of the prompt the writer was handed. The real figure needs the orchestrator to
  record the assembled prompt size. The place for it is built and waiting.
- **No PDF.** `outputs.formats` is markdown only on this branch.

## `npm test`

`smoke.mts` runs the real loaders and derivations against the committed run
under Node's type-stripping loader — the same modules the browser imports, not a
copy. It pins the acceptance criteria: four critic columns derived from data,
the two rejections and which critic caused them, 281,202 tokens, the cost
triple, the 51% critic share, the 24-versus-25 discrepancy, feasibility
rejecting an impossible target, and the dev server's allowlist refusing path
traversal.

That last group exists because of a real defect found while testing this:
`/data/output/../SECURITY.md` returned 200, because the allowlist was checked on
the path as requested and containment only afterwards. It now runs on the
normalised path. `main`'s SEC-3 makes the same point about checking containment
after resolving rather than before.
