import type {
  AgentCall,
  CostRange,
  CriticDisagreement,
  GateDecision,
  LogEntry,
  NovelConfig,
  Pricing,
  Provenance,
  RunState,
} from '../types'

// ------------------------------------------------------------ log filters

export const agentCalls = (log: LogEntry[]): AgentCall[] =>
  log.filter((e): e is AgentCall => e.kind === 'agent_call')

export const gateDecisions = (log: LogEntry[]): GateDecision[] =>
  log.filter((e): e is GateDecision => e.kind === 'gate_decision')

export const disagreements = (log: LogEntry[]): CriticDisagreement[] =>
  log.filter((e): e is CriticDisagreement => e.kind === 'critic_disagreement')

// ------------------------------------------------------------------- cost

const ZERO: CostRange = {
  low: 0,
  estimate: 0,
  high: 0,
  assumedInputShare: 0,
  unpriced: true,
}

/**
 * The cost of `tokens` on `model`, as a range.
 *
 * `low` and `high` are exact: every token at the input rate, and every token at
 * the output rate. The truth is somewhere between and cannot be narrowed,
 * because the harness reports one total with no split. `estimate` applies
 * `assumed_input_share` from `config/pricing.json`, which is a stated judgement.
 *
 * A model with no rate returns `unpriced`, and the panel shows tokens with no
 * cost. `config/pricing.json` puts it best: an absent cost is a gap a reader
 * can see; a wrong one is not.
 */
export function costOf(tokens: number, model: string | undefined, pricing: Pricing | null): CostRange {
  const rates = model ? pricing?.models?.[model] : undefined
  const share = pricing?.assumed_input_share
  if (!rates || share === undefined || !tokens) return ZERO

  const perInput = rates.input_per_mtok / 1_000_000
  const perOutput = rates.output_per_mtok / 1_000_000
  return {
    low: tokens * perInput,
    high: tokens * perOutput,
    estimate: tokens * (share * perInput + (1 - share) * perOutput),
    assumedInputShare: share,
    unpriced: false,
  }
}

export function addCost(a: CostRange, b: CostRange): CostRange {
  if (b.unpriced) return a
  return {
    low: a.low + b.low,
    estimate: a.estimate + b.estimate,
    high: a.high + b.high,
    assumedInputShare: b.assumedInputShare,
    unpriced: false,
  }
}

export interface TokenSummary {
  total: number
  byAgent: Array<{ agent: string; tokens: number; share: number; cost: CostRange }>
  cost: CostRange
  /** Distinct `tokens_source` values seen, so the panel can grade the total. */
  sources: Set<string>
  unpricedCalls: number
}

export function summariseTokens(log: LogEntry[], pricing: Pricing | null): TokenSummary {
  const calls = agentCalls(log)
  const total = calls.reduce((n, c) => n + (c.tokens ?? 0), 0)

  const perAgent = new Map<string, { tokens: number; cost: CostRange }>()
  let cost: CostRange = { ...ZERO, unpriced: true }
  let unpricedCalls = 0

  for (const call of calls) {
    const tokens = call.tokens ?? 0
    const c = costOf(tokens, call.model, pricing)
    if (c.unpriced && tokens) unpricedCalls += 1
    cost = addCost(cost, c)
    const prev = perAgent.get(call.agent) ?? { tokens: 0, cost: { ...ZERO } }
    perAgent.set(call.agent, { tokens: prev.tokens + tokens, cost: addCost(prev.cost, c) })
  }

  return {
    total,
    cost,
    unpricedCalls,
    sources: new Set(calls.filter((c) => c.tokens).map((c) => c.tokens_source ?? 'unlabelled')),
    byAgent: [...perAgent.entries()]
      .map(([agent, v]) => ({
        agent,
        tokens: v.tokens,
        share: total ? v.tokens / total : 0,
        cost: v.cost,
      }))
      .sort((a, b) => b.tokens - a.tokens),
  }
}

/** A token figure is only as good as how it was obtained. */
export function tokenProvenance(sources: Set<string>): Provenance {
  if (sources.size === 0) return 'absent'
  if (sources.has('reconstructed')) return 'reconstructed'
  return 'measured'
}

// ------------------------------------------------------------- gate table

export interface GateRow {
  chapter: number
  iteration: number
  scores: Record<string, number>
  aggregate: number
  threshold: number
  verdict: string
  /** Which critics produced the minimum — usually one, occasionally several. */
  worst: string[]
  note?: string
}

/**
 * The gate table, with its columns derived from the data.
 *
 * Deliberately not from `quality_gate.critics`: the config describes what the
 * next run will do, and this table describes what a past run did. They can
 * disagree, and when they do the data is what happened.
 */
export function gateTable(log: LogEntry[]): { critics: string[]; rows: GateRow[] } {
  const decisions = gateDecisions(log)
  const critics: string[] = []
  for (const d of decisions) {
    for (const name of Object.keys(d.scores)) {
      if (!critics.includes(name)) critics.push(name)
    }
  }

  const rows = decisions
    .map((d) => {
      const entries = Object.entries(d.scores)
      const min = entries.length ? Math.min(...entries.map(([, v]) => v)) : d.aggregate
      return {
        chapter: d.chapter,
        iteration: d.iteration,
        scores: d.scores,
        aggregate: d.aggregate,
        threshold: d.threshold,
        verdict: d.verdict,
        worst: entries.filter(([, v]) => v === min).map(([k]) => k),
        note: d.note,
      }
    })
    .sort((a, b) => a.chapter - b.chapter || a.iteration - b.iteration)

  return { critics, rows }
}

// --------------------------------------------------------- reconciliation

export interface Discrepancy {
  label: string
  values: Array<{ source: string; value: number | string }>
}

/**
 * Figures that ought to agree and do not.
 *
 * `state.json` says 25 calls and the log holds 24 rows with an `agent` field.
 * The panel shows both. Picking one silently would be the panel deciding which
 * of its own sources to believe, which is exactly the judgement a reader opened
 * it to make.
 */
export function discrepancies(state: RunState | null, log: LogEntry[]): Discrepancy[] {
  const out: Discrepancy[] = []
  const calls = agentCalls(log)
  const runComplete = log.find((e) => e.kind === 'run_event' && e.event === 'run_complete') as
    | { subagent_calls?: number }
    | undefined

  const claims: Array<{ source: string; value: number }> = [
    { source: 'rows with an agent field in agents.jsonl', value: calls.length },
  ]
  if (typeof state?.calls === 'number') claims.push({ source: 'state.json → calls', value: state.calls })
  if (typeof runComplete?.subagent_calls === 'number') {
    claims.push({ source: 'log → run_complete.subagent_calls', value: runComplete.subagent_calls })
  }
  if (new Set(claims.map((c) => c.value)).size > 1) {
    out.push({ label: 'subagent calls', values: claims })
  }

  // The manuscript word count, if two sources both claim one.
  const stateWords = state?.manuscript_words
  const assembled = log.find((e) => e.kind === 'run_event' && e.event === 'assemble') as
    | { words?: number }
    | undefined
  if (typeof stateWords === 'number' && typeof assembled?.words === 'number') {
    // These legitimately differ: the assembled book includes the synopsis.
    // Only reported when the gap is not the synopsis.
    const synopsis = state?.synopsis_words ?? 0
    if (Math.abs(assembled.words - stateWords - synopsis) > 2) {
      out.push({
        label: 'manuscript words',
        values: [
          { source: 'state.json → manuscript_words', value: stateWords },
          { source: 'log → assemble.words', value: assembled.words },
        ],
      })
    }
  }

  return out
}

// ------------------------------------------------------------ projections

export interface Projection {
  minCalls: number
  maxCalls: number
  minTokens: number
  maxTokens: number
  minCost: CostRange
  maxCost: CostRange
}

/**
 * What a configuration would cost, extrapolated from the measured run.
 *
 * The per-agent token averages come from a real run rather than from a guess,
 * which makes this an extrapolation rather than an invention — but it is still
 * an extrapolation from a three-chapter run, and a thirty-four-chapter one will
 * not behave identically. Shown as a range for that reason as well.
 */
export function project(
  chapters: number,
  maxRevisions: number,
  perChapterTokens: { writer: number; critics: number; style: number },
  setupTokens: number,
  pricing: Pricing | null,
  model = 'claude-opus-5',
): Projection {
  const minCalls = 2 + 1 + chapters * 3 + chapters + 1
  const maxCalls = 2 + 1 + chapters * 3 * (1 + maxRevisions) + chapters + 1

  const perChapterMin = perChapterTokens.writer + perChapterTokens.critics
  const perChapterMax = perChapterMin * (1 + maxRevisions)
  const minTokens = setupTokens + chapters * (perChapterMin + perChapterTokens.style)
  const maxTokens = setupTokens + chapters * (perChapterMax + perChapterTokens.style)

  return {
    minCalls,
    maxCalls,
    minTokens,
    maxTokens,
    minCost: costOf(minTokens, model, pricing),
    maxCost: costOf(maxTokens, model, pricing),
  }
}

/** Per-chapter token averages measured from a completed run. */
export function measuredPerChapter(log: LogEntry[]): {
  writer: number
  critics: number
  style: number
  setup: number
} {
  const calls = agentCalls(log)
  const sum = (pred: (c: AgentCall) => boolean) =>
    calls.filter(pred).reduce((n, c) => n + (c.tokens ?? 0), 0)
  const chapters = new Set(calls.filter((c) => c.chapter !== undefined).map((c) => c.chapter)).size || 1

  return {
    writer: sum((c) => c.agent === 'chapter-writer') / chapters,
    critics: sum((c) => c.agent.endsWith('-critic')) / chapters,
    style: sum((c) => c.agent === 'style-editor') / chapters,
    setup: sum((c) => ['worldbuilder', 'character-architect', 'plot-architect', 'publisher'].includes(c.agent)),
  }
}

// ----------------------------------------------------------- feasibility

export type Light = 'ok' | 'warn' | 'bad'

export interface Check {
  light: Light
  label: string
  detail: string
}

/** Mean characters per word, including the trailing space. */
const CHARS_PER_WORD = 5.5

/**
 * Whether a configuration is physically achievable.
 *
 * Nothing in the pipeline checks this today, and an impossible configuration is
 * not discovered until the length critic fails the same chapter three times in
 * a row and the gate accepts it with warnings. The arithmetic is crude — a line
 * budget against a word target — but crude and early beats exact and too late.
 */
export function feasibility(config: NovelConfig): Check[] {
  const checks: Check[] = []
  const novel = config.novel ?? {}
  const wpc = novel.words_per_chapter ?? {}
  const lines = novel.lines_per_chapter ?? {}
  const chars = novel.chars_per_line ?? {}

  const ordered = (r: Range | undefined, label: string) => {
    if (!r) return
    const { min, target, max } = r
    if (min !== undefined && max !== undefined && min > max) {
      checks.push({ light: 'bad', label, detail: `min ${min} is above max ${max}` })
      return
    }
    if (target !== undefined && min !== undefined && target < min) {
      checks.push({ light: 'bad', label, detail: `target ${target} is below min ${min}` })
      return
    }
    if (target !== undefined && max !== undefined && target > max) {
      checks.push({ light: 'bad', label, detail: `target ${target} is above max ${max}` })
    }
  }

  ordered(wpc, 'words per chapter')
  ordered(lines, 'lines per chapter')
  ordered(novel.paragraphs_per_chapter, 'paragraphs per chapter')
  ordered(novel.sentences_per_paragraph, 'sentences per paragraph')

  if (lines.max && chars.max && wpc.target) {
    const reachableMax = (lines.max * chars.max) / CHARS_PER_WORD
    const reachableMin = ((lines.min ?? 0) * chars.max) / CHARS_PER_WORD
    if (wpc.target > reachableMax) {
      checks.push({
        light: 'bad',
        label: 'target unreachable',
        detail: `${lines.max} lines × ${chars.max} chars holds about ${Math.round(reachableMax)} words, below the target of ${wpc.target}`,
      })
    } else if (wpc.target < reachableMin) {
      checks.push({
        light: 'warn',
        label: 'target below the line floor',
        detail: `${lines.min} lines is already about ${Math.round(reachableMin)} words, above the target of ${wpc.target}`,
      })
    } else {
      checks.push({
        light: 'ok',
        label: 'target fits the line budget',
        detail: `${Math.round(reachableMin)}–${Math.round(reachableMax)} words are reachable; target ${wpc.target}`,
      })
    }
  }

  const paras = novel.paragraphs_per_chapter
  const sentences = novel.sentences_per_paragraph
  if (paras?.max && sentences?.max && lines.max) {
    // One sentence rarely occupies less than a line at these widths.
    if (paras.max * (sentences.min ?? 1) > lines.max) {
      checks.push({
        light: 'warn',
        label: 'paragraphs against lines',
        detail: `${paras.max} paragraphs of at least ${sentences.min ?? 1} sentence need more than the ${lines.max}-line ceiling`,
      })
    }
  }

  const gate = config.quality_gate
  if (gate?.threshold !== undefined && (gate.threshold < 0 || gate.threshold > 10)) {
    checks.push({ light: 'bad', label: 'threshold', detail: `${gate.threshold} is outside 0–10` })
  }
  if (gate?.critics && gate.critics.length === 0) {
    checks.push({ light: 'bad', label: 'gate', detail: 'no critics: every draft passes' })
  }

  return checks
}

export function worstLight(checks: Check[]): Light {
  if (checks.some((c) => c.light === 'bad')) return 'bad'
  if (checks.some((c) => c.light === 'warn')) return 'warn'
  return 'ok'
}

type Range = { min?: number; max?: number; target?: number }

// ----------------------------------------------------------- deep merge

/** base → profile → user edits, merging objects and replacing arrays. */
export function deepMerge<T extends Record<string, unknown>>(base: T, overlay: Partial<T>): T {
  const out: Record<string, unknown> = { ...base }
  for (const [key, value] of Object.entries(overlay)) {
    if (value === undefined) continue
    const prev = out[key]
    if (
      value !== null &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      prev !== null &&
      typeof prev === 'object' &&
      !Array.isArray(prev)
    ) {
      out[key] = deepMerge(prev as Record<string, unknown>, value as Record<string, unknown>)
    } else {
      // Arrays replace wholesale, on purpose: a profile setting
      // outputs.formats to ["markdown"] means only markdown.
      out[key] = value
    }
  }
  return out as T
}

/** The delta of `candidate` against `base` — what a profile file would hold. */
export function deltaOf(base: unknown, candidate: unknown): unknown {
  if (
    base === null ||
    candidate === null ||
    typeof base !== 'object' ||
    typeof candidate !== 'object' ||
    Array.isArray(base) !== Array.isArray(candidate)
  ) {
    return JSON.stringify(base) === JSON.stringify(candidate) ? undefined : candidate
  }
  if (Array.isArray(candidate)) {
    return JSON.stringify(base) === JSON.stringify(candidate) ? undefined : candidate
  }
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(candidate as Record<string, unknown>)) {
    if (key.startsWith('_')) continue
    const diff = deltaOf((base as Record<string, unknown>)[key], value)
    if (diff !== undefined) out[key] = diff
  }
  return Object.keys(out).length ? out : undefined
}
