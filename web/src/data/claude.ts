import type { SampleFn } from './generate'

/**
 * Finding something that can ask Claude, wherever the panel is running.
 *
 * Two routes, and the page works with neither:
 *
 * 1. **The published artifact** grants the `sample` capability. `use('sample')`
 *    resolves it, or `null` when this view cannot run it — not served, not
 *    granted, or failed to load, and the three are indistinguishable by design.
 * 2. **The dev server's Claude Code route**, `/api/agent`, which runs each
 *    agent through `claude -p --agent <name>`. This is the best of the three
 *    and it is not close: the agent runs as a REAL SUBAGENT with the tool list
 *    from its own file, so the chapter writer has `Glob` and cannot reach a
 *    previous chapter — the guarantee holds by capability rather than by this
 *    page's discipline. It needs no API key, and Claude Code returns a real
 *    dollar cost.
 * 3. **The dev server's API route**, `/api/sample`, which forwards to the
 *    Anthropic API with a credential in the Node process. Real token counts,
 *    but the agents are prompts again.
 *
 * Preference order is 2, 1, 3 — capability first, then the published page,
 * then the raw API. Each says which one answered, because what a run can claim
 * about itself depends on it.
 */

declare global {
  interface Window {
    claude?: { use?: (name: string) => Promise<unknown> }
  }
}

export interface SampleSource {
  sample: SampleFn
  /** Which route answered, for the page to say so. */
  kind: 'claude-code' | 'artifact' | 'dev-server'
  /** True when the route returns real token counts. */
  reportsUsage: boolean
  /** True when the agents run as subagents with their real tool lists. */
  realSubagents: boolean
}

/** The artifact's capability, if this view has it. */
async function fromArtifact(): Promise<SampleSource | null> {
  try {
    const fn = await window.claude?.use?.('sample')
    if (typeof fn !== 'function') return null
    return { sample: fn as SampleFn, kind: 'artifact', reportsUsage: false, realSubagents: false }
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

  return { sample, kind: 'dev-server', reportsUsage: true, realSubagents: false }
}

/**
 * The Claude Code route. Needs the CLI on PATH and the agent files on disk;
 * needs no API key, because it uses the machine's own Claude Code session.
 */
async function fromClaudeCode(): Promise<SampleSource | null> {
  try {
    const probe = await fetch('api/agent')
    if (!probe.ok) return null
    const { available } = (await probe.json()) as { available?: boolean }
    if (!available) return null
  } catch {
    return null
  }

  /**
   * The separator `generate.ts` puts between an agent's system prompt and the
   * task it is given.
   */
  const SPLIT = '\n\n---\n\n'

  const sample: SampleFn = async (input, opts) => {
    // Only the task travels. `--agent <name>` gives the subagent its own system
    // prompt from its file, so sending that half again would say everything
    // twice — and the copy on disk is the one that governs its tools.
    const parts = input.split(SPLIT)
    const task = parts.length > 1 ? parts.slice(1).join(SPLIT) : input

    const res = await fetch('api/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent: opts?.agent, task }),
      signal: opts?.signal,
    })
    const body = (await res.json()) as {
      text?: string
      error?: string
      usage?: { input_tokens: number | null; output_tokens: number | null }
      cost_usd?: number | null
    }
    if (!res.ok || body.error) throw new Error(body.error ?? `agent call failed: ${res.status}`)
    return {
      text: body.text ?? '',
      usage: body.usage ?? undefined,
      cost_usd: body.cost_usd ?? undefined,
    }
  }

  return { sample, kind: 'claude-code', reportsUsage: true, realSubagents: true }
}

export async function getSampleSource(): Promise<SampleSource | null> {
  return (await fromClaudeCode()) ?? (await fromArtifact()) ?? (await fromDevServer())
}

/** Why no local route is usable, for the page to show verbatim. */
export async function devServerReason(): Promise<string | null> {
  // The Claude Code route is the one worth explaining: it needs no key.
  try {
    const probe = await fetch('api/agent')
    if (probe.ok) {
      const { available, reason } = (await probe.json()) as {
        available?: boolean
        reason?: string
      }
      if (available) return null
      if (reason) return reason
    }
  } catch {
    // fall through to the API route's own reason
  }

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
