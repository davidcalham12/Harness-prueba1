/**
 * Writes `output/runs.json` — the index the Library reads.
 *
 * A static page cannot list a directory. There is no server to answer "which
 * slugs are under output/", so the listing has to exist as a file, and
 * something has to write it.
 *
 * **This is a build script, not a backend.** It runs when you ask it to and
 * before `npm run build`; it is not running while anyone browses, it opens no
 * port, and it writes exactly one file at the top of `output/` — never inside a
 * run. The runs themselves stay untouched.
 *
 *     npm run index:runs
 *
 * Every field is derived from data that already exists. Nothing here is
 * invented, and where a run cannot supply something the field is null rather
 * than a zero — `has_state: false` marks a run that stopped before writing
 * `state.json`, which is a real state and not a broken one.
 */

import fs from 'node:fs'
import path from 'node:path'

const REPO_ROOT = path.resolve(import.meta.dirname, '..', '..')
const OUTPUT = path.join(REPO_ROOT, 'output')

const readJson = (p) => JSON.parse(fs.readFileSync(p, 'utf8'))

function readLog(dir) {
  const file = path.join(dir, 'logs', 'agents.jsonl')
  if (!fs.existsSync(file)) return []
  return fs
    .readFileSync(file, 'utf8')
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .flatMap((line) => {
      try {
        return [JSON.parse(line)]
      } catch {
        return []
      }
    })
}

/**
 * A run that never finished has no `state.json`, so everything the card needs
 * is reconstructed from the log. What cannot be reconstructed stays null.
 */
function describe(slug) {
  const dir = path.join(OUTPUT, slug)
  const log = readLog(dir)
  const statePath = path.join(dir, 'state.json')
  const hasState = fs.existsSync(statePath)
  const state = hasState ? readJson(statePath) : null

  const stamps = log.map((r) => r.ts).filter(Boolean).sort()
  const gate = log.filter((r) => r.event === 'gate_decision')
  const calls = log.filter((r) => r.agent)

  const chaptersFromLog = new Set(
    calls.filter((c) => typeof c.chapter === 'number').map((c) => c.chapter),
  ).size

  const snapshotPath = path.join(dir, 'config.snapshot.json')
  const snapshot = fs.existsSync(snapshotPath) ? readJson(snapshotPath) : null

  return {
    slug,
    premise: state?.premise ?? null,
    profile: state?.profile ?? snapshot?.profile ?? null,
    config_hash: state?.config_hash ?? snapshot?.config_hash ?? null,
    stage: state?.stage ?? (log.some((r) => r.event === 'run_complete') ? 'complete' : 'unknown'),
    chapters: state?.chapters?.length ?? (chaptersFromLog || null),
    manuscript_words: state?.manuscript_words ?? null,
    // The number a reader actually wants: how often the gate sent a draft back.
    retries: gate.filter((g) => g.verdict === 'retry').length,
    warnings:
      state?.chapters?.filter((c) => c.status === 'accepted_with_warnings').length ?? null,
    subagent_calls: calls.length,
    tokens: calls.reduce((n, c) => n + (c.tokens ?? 0), 0) || null,
    // Whether any token figure was reconstructed rather than recorded live.
    tokens_source: calls.some((c) => c.tokens && c.tokens_source === 'reconstructed')
      ? 'reconstructed'
      : calls.some((c) => c.tokens)
        ? 'measured'
        : null,
    started_at: stamps[0] ?? null,
    finished_at: stamps[stamps.length - 1] ?? null,
    has_state: hasState,
  }
}

function main() {
  if (!fs.existsSync(OUTPUT)) {
    console.error(`no output/ directory at ${OUTPUT} — nothing to index`)
    fs.mkdirSync(OUTPUT, { recursive: true })
  }

  const slugs = fs
    .readdirSync(OUTPUT, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    .filter((slug) => {
      const dir = path.join(OUTPUT, slug)
      // The log identifies a run, not state.json: an interrupted run has one
      // and not the other, and it still belongs in the library.
      return (
        fs.existsSync(path.join(dir, 'logs', 'agents.jsonl')) ||
        fs.existsSync(path.join(dir, 'state.json'))
      )
    })
    .sort()

  const runs = slugs.map(describe).sort((a, b) => {
    const at = a.finished_at ?? a.started_at ?? ''
    const bt = b.finished_at ?? b.started_at ?? ''
    return bt.localeCompare(at)
  })

  const manifest = { generated_at: new Date().toISOString(), runs }
  const target = path.join(OUTPUT, 'runs.json')
  fs.writeFileSync(target, JSON.stringify(manifest, null, 2) + '\n', 'utf8')

  console.log(`wrote ${path.relative(REPO_ROOT, target)} — ${runs.length} run(s)`)
  for (const run of runs) {
    console.log(
      `  ${run.slug.padEnd(34)} ${String(run.chapters ?? '?').padStart(2)} ch · ` +
        `${run.retries} retr${run.retries === 1 ? 'y' : 'ies'} · ` +
        `${run.has_state ? run.stage : 'no state.json'}`,
    )
  }
}

main()
