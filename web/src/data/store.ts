import type { GeneratedRun } from './generate'
import type { RunSummary } from '../types'
import { agentCalls, gateDecisions } from './derive'

/**
 * Keeping novels written in the page, so they are still there after a reload.
 *
 * The panel has no server and the artifact writes nothing to disk, so the only
 * place a generated novel can live is the viewer's own browser. `localStorage`
 * is that place, with its limits stated rather than assumed:
 *
 * * **It is per viewer and per browser.** What you write here never reaches
 *   another person, another device, or Claude. Two people opening the same
 *   published page see different libraries.
 * * **It can fail.** A private window, cleared site data, a quota — any of
 *   these makes a read come back empty or a write throw. Every call is
 *   wrapped, and the panel works with none of it: an unsaved run is still
 *   shown for the rest of the session.
 *
 * So this is a convenience, not a guarantee, and the Library says so on every
 * run it restores. A novel that must survive belongs in `dist/book.md` on
 * someone's disk, which is what the terminal route produces.
 */

const KEY = 'novaforge.runs.v1'

/** Enough novels to compare, few enough to stay inside a browser quota. */
const KEEP = 12

interface Stored {
  savedAt: string
  run: GeneratedRun
}

function readAll(): Stored[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as Stored[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeAll(items: Stored[]): boolean {
  try {
    localStorage.setItem(KEY, JSON.stringify(items))
    return true
  } catch {
    // Almost always the quota. Dropping the oldest and trying once is worth it;
    // failing after that is reported to the caller rather than swallowed.
    try {
      localStorage.setItem(KEY, JSON.stringify(items.slice(0, Math.max(1, items.length - 1))))
      return true
    } catch {
      return false
    }
  }
}

export function loadStoredRuns(): GeneratedRun[] {
  return readAll().map((s) => s.run)
}

/** Returns false when the browser would not keep it; the run is still usable. */
export function storeRun(run: GeneratedRun): boolean {
  const existing = readAll().filter((s) => s.run.slug !== run.slug)
  return writeAll([{ savedAt: new Date().toISOString(), run }, ...existing].slice(0, KEEP))
}

export function forgetRun(slug: string): void {
  writeAll(readAll().filter((s) => s.run.slug !== slug))
}

export function storedAt(slug: string): string | null {
  return readAll().find((s) => s.run.slug === slug)?.savedAt ?? null
}

/**
 * A generated run described the way `output/runs.json` describes a saved one,
 * so the Library can list both from one shape and needs no special case.
 */
export function summarise(run: GeneratedRun): RunSummary {
  const calls = agentCalls(run.log)
  const stamps = run.log.map((e) => e.ts).filter(Boolean).sort() as string[]
  const tokens = calls.reduce((n, c) => n + (c.tokens ?? 0), 0)

  return {
    slug: run.slug,
    premise: run.state.premise,
    profile: run.state.profile,
    config_hash: run.state.config_hash,
    stage: run.state.stage,
    chapters: run.state.chapters.length,
    manuscript_words: run.state.manuscript_words ?? null,
    retries: gateDecisions(run.log).filter((g) => g.verdict === 'retry').length,
    warnings: run.state.chapters.filter((c) => c.status === 'accepted_with_warnings').length,
    subagent_calls: calls.length,
    tokens: tokens || null,
    // Measured characters, converted by a rule of thumb. Not the same claim as
    // a figure a harness reported, and graded apart from one.
    tokens_source: tokens ? 'estimated' : null,
    started_at: stamps[0] ?? null,
    finished_at: stamps[stamps.length - 1] ?? null,
    has_state: true,
  }
}
