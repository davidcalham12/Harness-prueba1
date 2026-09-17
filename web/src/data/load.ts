import { parse as parseYaml } from 'yaml'
import type {
  AgentCall,
  AgentDef,
  Critique,
  FlowSpec,
  LogEntry,
  NovelConfig,
  Pricing,
  RunState,
} from '../types'

/** Everything is fetched from `/data/<repo-relative-path>`. See vite.config.ts. */
const DATA = 'data/'

export class MissingFile extends Error {
  /** Written out rather than as a parameter property, so this module runs
   *  unchanged under Node's type-stripping loader — which is what lets
   *  `npm test` exercise the real loaders instead of a copy of them. */
  readonly path: string

  constructor(path: string) {
    super(`not found: ${path}`)
    this.path = path
  }
}

async function text(rel: string): Promise<string> {
  const res = await fetch(DATA + rel)
  if (!res.ok) throw new MissingFile(rel)
  return res.text()
}

async function json<T>(rel: string): Promise<T> {
  return JSON.parse(await text(rel)) as T
}

/** Absent is a normal state for several of these files, not an error. */
async function optional<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load()
  } catch (err) {
    if (err instanceof MissingFile) return null
    throw err
  }
}

// ------------------------------------------------------------------- runs

export async function loadRuns(): Promise<string[]> {
  return optional(() => json<string[]>('runs.json')).then((r) => r ?? [])
}

/**
 * `state.json` is written when a run finishes, so an interrupted run has none.
 * Callers must cope with null rather than assume it.
 */
export async function loadState(slug: string): Promise<RunState | null> {
  return optional(() => json<RunState>(`output/${slug}/state.json`))
}

// -------------------------------------------------------------------- log

/**
 * Turns each JSONL line into a discriminated union member.
 *
 * The discriminator is not one field: a call is identified by carrying
 * `agent`, and everything else by its `event`. Modelling it as one type with
 * everything optional would make every consumer re-derive that test.
 */
export function classify(row: Record<string, unknown>): LogEntry {
  if (typeof row.agent === 'string') {
    return { kind: 'agent_call', ...row } as AgentCall
  }
  switch (row.event) {
    case 'gate_decision':
      return { kind: 'gate_decision', ...row } as LogEntry
    case 'critic_disagreement':
      return { kind: 'critic_disagreement', ...row } as LogEntry
    case 'stage_complete':
      return { kind: 'stage_complete', ...row } as LogEntry
    default:
      return { kind: 'run_event', ...row } as LogEntry
  }
}

export async function loadLog(slug: string): Promise<LogEntry[]> {
  const raw = await optional(() => text(`output/${slug}/logs/agents.jsonl`))
  if (raw === null) return []
  const entries: LogEntry[] = []
  for (const line of raw.split('\n')) {
    if (!line.trim()) continue
    try {
      entries.push(classify(JSON.parse(line)))
    } catch {
      // A malformed line is skipped rather than fatal: a partial log from an
      // interrupted run is still worth reading.
    }
  }
  return entries
}

// -------------------------------------------------------------- critiques

/**
 * Which critique files exist is derived from the log's gate decisions, because
 * the set of critics is a property of the run and not of the config. A chapter
 * judged by a different set than its neighbour is legal.
 */
export async function loadCritiques(
  slug: string,
  wanted: Array<{ chapter: number; critic: string }>,
): Promise<Critique[]> {
  const results = await Promise.all(
    wanted.map(({ chapter, critic }) =>
      optional(() =>
        json<Critique>(
          `output/${slug}/critiques/ch${String(chapter).padStart(2, '0')}.${critic}.json`,
        ),
      ),
    ),
  )
  return results.filter((c): c is Critique => c !== null)
}

// ----------------------------------------------------------------- config

export async function loadBaseConfig(): Promise<NovelConfig> {
  return json<NovelConfig>('config/novel.config.json')
}

export async function loadProfile(name: string): Promise<NovelConfig | null> {
  return optional(() => json<NovelConfig>(`config/profiles/${name}.json`))
}

export async function loadSnapshot(slug: string): Promise<NovelConfig | null> {
  return optional(() => json<NovelConfig>(`output/${slug}/config.snapshot.json`))
}

export async function loadPricing(): Promise<Pricing | null> {
  return optional(() => json<Pricing>('config/pricing.json'))
}

/** The four shipped profiles. Probed rather than hard-coded. */
export const PROFILE_NAMES = ['tiny', 'small', 'medium', 'full']

// -------------------------------------------------------------- flow spec

/**
 * Parsed, never transcribed. The repository's own comment on this file says it
 * is the contract: reorder the stages or change a threshold and the next run
 * behaves differently with no code change. A panel with the stage list written
 * into TypeScript would silently stop telling the truth the day that happens.
 */
export async function loadFlow(): Promise<FlowSpec> {
  const parsed = parseYaml(await text('specs/flow.yaml')) as FlowSpec
  if (!parsed?.stages?.length) throw new Error('specs/flow.yaml has no stages')
  return parsed
}

// ---------------------------------------------------------------- agents

/** `---\nkey: value\n---\nbody` — the front matter Claude Code itself reads. */
export function parseFrontMatter(source: string): { meta: Record<string, string>; body: string } {
  const match = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/.exec(source)
  if (!match) return { meta: {}, body: source }
  const meta: Record<string, string> = {}
  for (const line of match[1]!.split(/\r?\n/)) {
    const sep = line.indexOf(':')
    if (sep <= 0) continue
    meta[line.slice(0, sep).trim()] = line.slice(sep + 1).trim()
  }
  return { meta, body: match[2] ?? '' }
}

/**
 * The agent definitions, read from the files that actually configure them.
 *
 * `tools` is the authority model of the whole system, so it is read from the
 * same bytes Claude Code reads rather than copied into a constant here. The
 * names come from the flow spec, so an agent added to the pipeline appears
 * without touching this file.
 */
export async function loadAgents(names: string[]): Promise<AgentDef[]> {
  const files = await Promise.all(
    names.map((n) => optional(() => text(`.claude/agents/${n}.md`)).then((t) => [n, t] as const)),
  )
  const defs: AgentDef[] = []
  for (const [name, source] of files) {
    if (source === null) continue
    const { meta, body } = parseFrontMatter(source)
    defs.push({
      name: meta.name ?? name,
      description: meta.description,
      // An absent or empty `tools:` means the agent inherits everything, which
      // is a different claim from "no tools" and must not be shown as none.
      tools:
        meta.tools === undefined
          ? []
          : meta.tools
              .split(',')
              .map((t) => t.trim())
              .filter(Boolean),
      model: meta.model,
      body,
    })
  }
  return defs
}

// ------------------------------------------------------------- manuscript

export async function loadDoc(slug: string, rel: string): Promise<string | null> {
  return optional(() => text(`output/${slug}/${rel}`))
}
