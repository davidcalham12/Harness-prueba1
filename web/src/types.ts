/**
 * The shapes the pipeline writes.
 *
 * Every type here mirrors a file the orchestrator produces. Where a field is
 * optional it is optional in the data too — nothing is widened for
 * convenience, because a field that is sometimes absent is exactly the thing
 * the panel has to show as "not recorded" rather than as zero.
 */

// ---------------------------------------------------------------- provenance

/**
 * How a number came to be known. The repository marks every claim with how it
 * was established (`specs/acceptance.md` does it criterion by criterion) and
 * the panel inherits that discipline: no figure is rendered without one.
 */
export type Provenance =
  /** The orchestrator counted it — `wc -w`, a heading scan, a file length. */
  | 'measured'
  /** The agent said it about itself. The worldbuilder reported ~870 words
   *  when there were 948, so this grade is a warning, not a detail. */
  | 'reported'
  /** Copied out of a session transcript after the fact. */
  | 'reconstructed'
  /** Derived from something that was measured — tokens from a character
   *  count, for instance. The input is real; the conversion is a rule. */
  | 'estimated'
  /** The data does not carry it. */
  | 'absent'

export interface Sourced<T> {
  value: T
  provenance: Provenance
  /** Optional one-line explanation, shown on hover. */
  note?: string
}

// ------------------------------------------------------------------- state

export type ChapterStatus = 'approved' | 'accepted_with_warnings'

export interface ChapterState {
  n: number
  status: ChapterStatus
  drafts: number
  words: number
  scores: Record<string, number>
}

/** `output/<slug>/state.json`. Only written when a run completes. */
export interface RunState {
  slug: string
  premise: string
  profile: string | null
  config_hash: string
  stage: string
  chapters: ChapterState[]
  style_passes_discarded?: number
  manuscript_words?: number
  synopsis_words?: number
  calls?: number
}

// --------------------------------------------------------------------- log

export type AgentVerdict = 'draft' | 'score' | 'accepted' | 'rejected' | 'pending'

/** A line with an `agent` field: one subagent call. */
export interface AgentCall {
  kind: 'agent_call'
  /** Characters sent and received. Recorded by a run written in the page,
   *  which assembles the prompts itself and can therefore count them. A run
   *  from Claude Code has neither: the harness reports tokens instead. */
  prompt_chars?: number
  output_chars?: number
  ts?: string
  stage?: string
  agent: string
  chapter?: number
  iteration?: number
  config_hash?: string
  verdict?: AgentVerdict | string
  words?: number
  score?: number
  findings?: number
  tokens?: number
  tokens_source?: string
  model?: string
  note?: string
  reason?: string
}

export type GateVerdict = 'accept' | 'retry' | 'accept_with_warnings'

export interface GateDecision {
  kind: 'gate_decision'
  ts?: string
  stage?: string
  chapter: number
  iteration: number
  config_hash?: string
  scores: Record<string, number>
  aggregate: number
  threshold: number
  verdict: GateVerdict | string
  note?: string
}

/**
 * Two critics reached different verdicts on the same text and the orchestrator
 * ruled. Rare, and the single most informative row a run can produce.
 */
export interface CriticDisagreement {
  kind: 'critic_disagreement'
  ts?: string
  chapter: number
  iteration: number
  subject: string
  continuity?: string
  science?: string
  orchestrator_ruling: string
}

export interface StageComplete {
  kind: 'stage_complete'
  ts?: string
  stage?: string
  config_hash?: string
  chapters_approved?: number
  chapters_with_warnings?: number
  passes_discarded?: number
  [extra: string]: unknown
}

export interface RunEvent {
  kind: 'run_event'
  ts?: string
  event: string
  stage?: string
  config_hash?: string
  subagent_calls?: number
  chapters_approved?: number
  chapters_with_warnings?: number
  artefact?: string
  words?: number
  note?: string
  [extra: string]: unknown
}

export type LogEntry =
  | AgentCall
  | GateDecision
  | CriticDisagreement
  | StageComplete
  | RunEvent

// --------------------------------------------------------------- critiques

export interface Finding {
  kind: string
  severity: 'high' | 'medium' | 'low' | string
  /** False when the orchestrator examined the finding and rejected it. */
  upheld?: boolean
  quote?: string
  fix?: string
  claim?: string
  reference?: string
  orchestrator_ruling?: string
}

export interface CritiqueIteration {
  iteration: number
  score: number
  findings?: Finding[]
  measured_words?: number
  first_line?: string
}

export interface Critique {
  critic: string
  chapter: number
  /** `model` critics are subagents and do not reproduce; `arithmetic` ones do. */
  kind: 'model' | 'arithmetic' | string
  agent?: string
  drafts?: number
  band?: { min: number; max: number; target?: number }
  rule?: string
  iterations: CritiqueIteration[]
  final?: { score: number; findings?: Finding[] }
  notes?: string[]
  repair?: string
}

// ------------------------------------------------------------------ config

export interface Range {
  min?: number
  max?: number
  target?: number
}

export interface NovelConfig {
  profile?: string | null
  novel?: {
    chapters?: number
    tone?: string
    words_per_chapter?: Range
    tolerance_pct?: number
    paragraphs_per_chapter?: Range
    sentences_per_paragraph?: Range
    lines_per_chapter?: Range
    chars_per_line?: Range
    beats_per_chapter?: Range
    promises?: Range
    [k: string]: unknown
  }
  bible?: Record<string, number | Range>
  context?: { max_summary_words?: number; forbid_prior_chapter_prose?: boolean }
  quality_gate?: {
    critics?: string[]
    threshold?: number
    max_revisions?: number
    aggregate?: string
    on_fail?: string
  }
  style?: { word_count_tolerance_pct?: number }
  budget?: { max_cost_usd?: number; max_calls?: number; max_tokens?: number }
  outputs?: Record<string, unknown>
  [k: string]: unknown
}

export interface Pricing {
  assumed_input_share?: number
  models?: Record<string, { input_per_mtok: number; output_per_mtok: number }>
  _source?: string
}

// -------------------------------------------------------------- flow spec

export interface FlowGate {
  critics?: string[]
  threshold?: number
  max_iterations?: number
  aggregate?: string
}

export interface FlowStage {
  id: string
  name: string
  agent: string
  description?: string
  inputs?: string[]
  outputs?: string[]
  writes_bible?: boolean
  gate?: FlowGate | null
  on_fail?: string
  foreach?: string
  context_policy?: {
    forbid_prior_chapter_prose?: boolean
    max_summary_words?: number
  }
}

export interface FlowSpec {
  version?: number
  name?: string
  description?: string
  defaults?: Record<string, unknown>
  stages: FlowStage[]
}

// ----------------------------------------------------------------- agents

/** Parsed from the YAML front matter of `.claude/agents/<name>.md`. */
export interface AgentDef {
  name: string
  description?: string
  /** The tool list IS the authority model. An empty list means no tools. */
  tools: string[]
  model?: string
  /** The prose body of the agent file — its system prompt. */
  body: string
}

// -------------------------------------------------------------- cost model

/**
 * What a call cost, as a range.
 *
 * The harness reports one token total per subagent call with no input/output
 * split, so cost cannot be computed — only bounded. `low` and `high` are exact
 * arithmetic; `estimate` rests on `assumed_input_share`, which is a declared
 * assumption and not a measurement. The panel renders all three, always.
 */
export interface CostRange {
  low: number
  estimate: number
  high: number
  assumedInputShare: number
  /** True when no rate was found for the model; then all three are zero. */
  unpriced: boolean
}

// ------------------------------------------------------------- run index

/** One row of `output/runs.json`, written by `npm run index:runs`. */
export interface RunSummary {
  slug: string
  premise: string | null
  profile: string | null
  config_hash: string | null
  stage: string
  chapters: number | null
  manuscript_words: number | null
  retries: number
  warnings: number | null
  subagent_calls: number
  tokens: number | null
  tokens_source: string | null
  started_at: string | null
  finished_at: string | null
  /** False when the run stopped before writing state.json. A real state. */
  has_state: boolean
}

export interface RunIndex {
  generated_at: string
  runs: RunSummary[]
}

// -------------------------------------------------------- the orchestrator

/**
 * The ninth actor.
 *
 * The eight agents are subagents, each in its own context window. The
 * orchestrator is the Claude Code session that dispatches them, and it is not
 * a gap between the boxes: it runs two of the four critics itself, makes every
 * gate decision, overrules a critic when one is wrong, rejects an agent's work
 * before the gate ever sees it, writes the rolling summaries the chapter
 * writer is fed, and assembles the book in the shell.
 *
 * It is also what makes the central guarantee true. The chapter writer has
 * `Glob` and cannot fetch anything; what reaches it is whatever the
 * orchestrator put in the prompt.
 */
export const ORCHESTRATOR = 'orchestrator' as const

/** Everything the orchestrator did in a run, counted from the log. */
export interface OrchestratorActivity {
  gateDecisions: number
  disagreementsArbitrated: number
  preGateRejections: number
  /** Critics it ran itself — the two that reproduce. */
  criticsRunLocally: string[]
  assemblies: number
  stagesCompleted: number
  /** Events attributed to it, i.e. every log row with no `agent` field. */
  events: number
}
