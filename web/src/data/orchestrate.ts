/**
 * Watching a run that Claude Code is orchestrating.
 *
 * The page does not drive this one. It starts `/api/run`, then polls for the
 * event stream and reads what is happening out of it. When the run finishes,
 * the artefacts are on disk under `output/<slug>/` and the Library picks them
 * up like any other run — which is the point: one pipeline, not two.
 *
 * Progress here is **inferred, not counted**. The panel's own generator knows
 * how many calls it will make; this one is reading someone else's work over its
 * shoulder, so the step it reports is the last thing it recognised rather than
 * a position in a plan. A line that says "reading the outline" means an event
 * said so, not that a counter advanced.
 */

export interface RunEventFeed {
  done: boolean
  error?: string
  total: number
  elapsed_ms: number
  events: StreamEvent[]
}

/**
 * The shapes Claude Code emits on `--output-format stream-json`.
 *
 * Observed from a real run rather than assumed: `system/init`,
 * `system/thinking_tokens`, `system/permission_denied`, `assistant`, `user`,
 * `rate_limit_event` and a final `result`. Anything unrecognised is ignored
 * rather than treated as an error — the stream is someone else's and may grow
 * shapes this panel has never seen.
 */
export type StreamEvent =
  | { type: 'system'; subtype?: string; model?: string; slash_commands?: string[]; tools?: string[] }
  | { type: 'assistant'; message?: { content?: ContentBlock[] } }
  | { type: 'user'; message?: { content?: ContentBlock[] } }
  | {
      type: 'result'
      subtype?: string
      total_cost_usd?: number
      usage?: { input_tokens?: number; output_tokens?: number }
      num_turns?: number
      is_error?: boolean
      result?: string
      subagent_stats?: { spawned?: number; completed?: number; failed?: number }
    }
  | { type: string; [k: string]: unknown }

interface ContentBlock {
  type: string
  text?: string
  name?: string
  input?: Record<string, unknown>
}

export interface RunProgress {
  /** The most recent thing the panel could name. */
  headline: string
  /** Subagents dispatched so far, by name. */
  dispatched: string[]
  /** Files the run has written. */
  written: string[]
  /** Populated when the run ends. */
  finished?: {
    ok: boolean
    costUsd?: number
    turns?: number
    subagents?: { spawned?: number; completed?: number; failed?: number }
    summary?: string
  }
  elapsedMs: number
}

export async function startRun(premise: string, profile: string): Promise<string> {
  const res = await fetch('api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ premise, profile }),
  })
  const body = (await res.json()) as { id?: string; error?: string }
  if (!res.ok || !body.id) throw new Error(body.error ?? `could not start: ${res.status}`)
  return body.id
}

export async function stopRun(id: string): Promise<void> {
  await fetch(`api/run/${id}/stop`, { method: 'POST' })
}

export async function pollRun(id: string, since: number): Promise<RunEventFeed> {
  const res = await fetch(`api/run/${id}?since=${since}`)
  if (!res.ok) throw new Error(`the run could not be read: ${res.status}`)
  return (await res.json()) as RunEventFeed
}

/** Whether Claude Code on this machine has the skill registered. */
export async function skillAvailable(): Promise<boolean> {
  try {
    const res = await fetch('api/agent')
    if (!res.ok) return false
    return Boolean(((await res.json()) as { available?: boolean }).available)
  } catch {
    return false
  }
}

/**
 * Reads a batch of events into something a person can watch.
 *
 * Fold it over the accumulating stream: each call takes the previous progress
 * and the new events, because the interesting facts are spread across the
 * stream rather than restated in each event.
 */
export function readProgress(previous: RunProgress, events: StreamEvent[]): RunProgress {
  const next: RunProgress = { ...previous, dispatched: [...previous.dispatched], written: [...previous.written] }

  for (const event of events) {
    if (event.type === 'system' && 'subtype' in event && event.subtype === 'init') {
      next.headline = 'Claude Code started and loaded the skill'
      continue
    }

    if (event.type === 'assistant' || event.type === 'user') {
      const blocks = (event as { message?: { content?: ContentBlock[] } }).message?.content ?? []
      for (const block of blocks) {
        if (block.type === 'text' && block.text?.trim()) {
          // The orchestrator narrating itself is the best headline available.
          const line = block.text.trim().split('\n').find((l) => l.trim().length > 12)
          if (line) next.headline = line.slice(0, 160)
        }
        if (block.type === 'tool_use' && block.name) {
          // Claude Code names this tool `Agent`; `Task` is the older spelling
          // and both are accepted, because guessing one of them wrong shows up
          // as a run that dispatched nothing.
          if (block.name === 'Agent' || block.name === 'Task') {
            const agent =
              (block.input?.subagent_type as string) ?? (block.input?.description as string) ?? 'a subagent'
            next.dispatched.push(agent)
            next.headline = `dispatched ${agent}`
          } else if (block.name === 'Write' || block.name === 'Edit') {
            const file = String(block.input?.file_path ?? '')
            const short = file.split(/[/\\]/).slice(-2).join('/')
            if (short) {
              next.written.push(short)
              next.headline = `wrote ${short}`
            }
          }
        }
      }
      continue
    }

    if (event.type === 'result') {
      const r = event as Extract<StreamEvent, { type: 'result' }>
      next.finished = {
        ok: !r.is_error,
        costUsd: r.total_cost_usd,
        turns: r.num_turns,
        subagents: r.subagent_stats,
        summary: r.result?.slice(0, 600),
      }
      next.headline = r.is_error ? 'the run reported an error' : 'finished'
    }
  }

  return next
}

export const emptyProgress: RunProgress = {
  headline: 'starting',
  dispatched: [],
  written: [],
  elapsedMs: 0,
}
