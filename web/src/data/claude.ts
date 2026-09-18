import type { SampleFn } from './generate'

/**
 * Finding something that can ask Claude, wherever the panel is running.
 *
 * Two routes, and the page works with neither:
 *
 * 1. **The published artifact** grants the `sample` capability. `use('sample')`
 *    resolves it, or `null` when this view cannot run it — not served, not
 *    granted, or failed to load, and the three are indistinguishable by design.
 * 2. **The dev server** exposes `/api/sample`, which forwards to the Anthropic
 *    API using a credential held in the Node process. It exists only while
 *    `npm run dev` is running and is never part of a build.
 *
 * The second is the better of the two for one reason: the real API reports
 * token usage, so a local run has measured tokens where the artifact can only
 * estimate them from characters. The panel grades those apart.
 */

declare global {
  interface Window {
    claude?: { use?: (name: string) => Promise<unknown> }
  }
}

export interface SampleSource {
  sample: SampleFn
  /** Which route answered, for the page to say so. */
  kind: 'artifact' | 'dev-server'
  /** True when the route returns real token counts. */
  reportsUsage: boolean
}

/** The artifact's capability, if this view has it. */
async function fromArtifact(): Promise<SampleSource | null> {
  try {
    const fn = await window.claude?.use?.('sample')
    if (typeof fn !== 'function') return null
    return { sample: fn as SampleFn, kind: 'artifact', reportsUsage: false }
  } catch {
    return null
  }
}

/** The dev server's route, if it is there and holds a credential. */
async function fromDevServer(): Promise<SampleSource | null> {
  try {
    const probe = await fetch('api/sample')
    if (!probe.ok) return null
    const { available } = (await probe.json()) as { available?: boolean; reason?: string }
    if (!available) return null
  } catch {
    return null
  }

  const sample: SampleFn = async (input, opts) => {
    const res = await fetch('api/sample', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: input, model: opts?.model }),
      signal: opts?.signal,
    })
    const body = (await res.json()) as {
      text?: string
      error?: string
      usage?: { input_tokens: number | null; output_tokens: number | null }
    }
    if (!res.ok || body.error) throw new Error(body.error ?? `sample failed: ${res.status}`)
    return {
      text: body.text ?? '',
      usage: body.usage ?? undefined,
    }
  }

  return { sample, kind: 'dev-server', reportsUsage: true }
}

export async function getSampleSource(): Promise<SampleSource | null> {
  return (await fromArtifact()) ?? (await fromDevServer())
}

/** Why the dev server cannot sample, for the page to show verbatim. */
export async function devServerReason(): Promise<string | null> {
  try {
    const probe = await fetch('api/sample')
    if (!probe.ok) return null
    const { available, reason } = (await probe.json()) as { available?: boolean; reason?: string }
    return available ? null : (reason ?? null)
  } catch {
    return null
  }
}

export {}
