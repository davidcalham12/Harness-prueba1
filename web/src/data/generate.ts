import type {
  AgentDef,
  Critique,
  CritiqueIteration,
  Finding,
  FlowSpec,
  LogEntry,
  NovelConfig,
  RunState,
} from '../types'
import { slugifyPremise } from './derive'

/**
 * Running the pipeline inside the published page.
 *
 * Everywhere else this panel is read-only, and the reason was never squeamishness:
 * the orchestrator is a Claude Code session in a terminal, and a browser button
 * had nothing to call. A published artifact does — the `sample` capability lets
 * the page ask Claude directly — so this module is the orchestration procedure
 * from `.claude/skills/novaforge/SKILL.md`, rewritten to run here.
 *
 * **Three things are genuinely different, and the page says all three.**
 *
 * 1. **The agents are prompts, not subagents.** In Claude Code each agent is a
 *    subagent with its own context window and its own tool list, and the
 *    chapter writer's `tools: Glob` makes prior prose *unreachable* — a
 *    capability, not a promise. Here every call is a sampling request from one
 *    page. The context policy still holds, because this module assembles each
 *    prompt and never puts prior prose in the writer's, but it holds by
 *    discipline rather than by construction. That is the orchestrator's half of
 *    the guarantee without the agent's half.
 *
 * 2. **Nothing is written to disk.** The run exists in memory and is rendered
 *    by the same screens as a run from `output/`. Reload and it is gone.
 *
 * 3. **Tokens are estimated, not reported.** `sample` returns text and no usage,
 *    so there is no token count to record. What this module *can* do is count
 *    the characters it sends and receives, because it assembles every prompt
 *    itself — and that is exact. Tokens follow at roughly four characters each,
 *    which is a rule of thumb; every such figure is graded `estimated` and says
 *    so. The character counts also give the context chart the measurement it
 *    has always wanted: the size of the prompt the writer was actually handed,
 *    rather than the tokens a subagent happened to consume.
 *
 * The agents' wording is not reinvented: the system prompts come from the same
 * `.claude/agents/*.md` bodies the panel already loads.
 */

export interface SampleFn {
  (input: string, opts?: { onText?: (e: { text: string }) => void; signal?: AbortSignal }): Promise<{
    text: string
  }>
  json?: <T>(input: string, opts?: { signal?: AbortSignal }) => Promise<T>
}

export interface GeneratedRun {
  slug: string
  state: RunState
  log: LogEntry[]
  critiques: Critique[]
  /** Path relative to the run directory → contents. The Manuscript reads these. */
  docs: Record<string, string>
}

export interface Progress {
  stage: string
  detail: string
  done: number
  total: number
}

const pad = (n: number) => String(n).padStart(2, '0')

/**
 * The 12-hex-digit identity of a configuration, the way CFG-8 defines it:
 * SHA-256 of the resolved config as canonical JSON, sorted keys, no
 * whitespace, `_comment` stripped. The same settings hash the same anywhere,
 * which is what makes "these two runs differed only in the config" checkable.
 */
async function configHash(config: unknown): Promise<string> {
  const strip = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(strip)
    if (value && typeof value === 'object') {
      const out: Record<string, unknown> = {}
      for (const key of Object.keys(value as Record<string, unknown>).sort()) {
        if (key.startsWith('_')) continue
        out[key] = strip((value as Record<string, unknown>)[key])
      }
      return out
    }
    return value
  }
  const canonical = JSON.stringify(strip(config))
  try {
    const bytes = new TextEncoder().encode(canonical)
    const digest = await crypto.subtle.digest('SHA-256', bytes)
    return [...new Uint8Array(digest)]
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('')
      .slice(0, 12)
  } catch {
    // Without SubtleCrypto there is no hash to give, and a made-up one would
    // be worse than none: it would claim an identity it cannot support.
    return 'unhashed'
  }
}
const now = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z')
const words = (s: string) => s.trim().split(/\s+/).filter(Boolean).length

/** The system prompt an agent file carries, below its front matter. */
function promptOf(agents: AgentDef[], name: string): string {
  const agent = agents.find((a) => a.name === name)
  if (!agent) throw new Error(`no agent definition for ${name}`)
  // The file is documentation *and* prompt; the section after "## System
  // prompt" is the prompt where one is marked, and the whole body otherwise.
  const marked = /##\s*System prompt\s*\n([\s\S]*)$/i.exec(agent.body)
  return (marked?.[1] ?? agent.body).trim()
}

/** Strip a code fence and any preamble before the first heading. */
function cleanChapter(text: string): string {
  let out = text.trim()
  const fence = /^```[a-z]*\n([\s\S]*?)\n```$/i.exec(out)
  if (fence) out = fence[1]!.trim()
  const heading = out.indexOf('# Chapter')
  if (heading > 0) out = out.slice(heading)
  return out.trim()
}

function parseOutlineEntries(outline: string, expected: number): string[] {
  const parts = outline.split(/^###\s+Chapter\s+\d+\s*[—-]\s*/m)
  const entries = parts.slice(1)
  if (entries.length >= expected) return entries.slice(0, expected)
  // A malformed outline is reported rather than silently under-filled.
  throw new Error(
    `the outline split into ${entries.length} chapter entries, not ${expected}. ` +
      `The plot architect must use "### Chapter N — Title" exactly.`,
  )
}

/** Titles, for the chapter headings. */
function outlineTitles(outline: string): string[] {
  return [...outline.matchAll(/^###\s+Chapter\s+\d+\s*[—-]\s*(.+)$/gm)].map((m) => m[1]!.trim())
}

export interface GenerateOptions {
  premise: string
  config: NovelConfig
  profile: string
  agents: AgentDef[]
  flow: FlowSpec
  sample: SampleFn
  onProgress: (p: Progress) => void
  signal?: AbortSignal
}

export async function generateNovel(options: GenerateOptions): Promise<GeneratedRun> {
  const { premise, config, profile, agents, sample, onProgress, signal } = options

  const novel = config.novel ?? {}
  const bible = config.bible ?? {}
  const gate = config.quality_gate ?? {}
  const chapters = novel.chapters ?? 3
  const threshold = gate.threshold ?? 8
  const maxRevisions = gate.max_revisions ?? 2
  const tolerance = (novel.tolerance_pct ?? 20) / 100
  const bandMin = Math.round((novel.words_per_chapter?.min ?? 300) * (1 - tolerance))
  const bandMax = Math.round((novel.words_per_chapter?.max ?? 550) * (1 + tolerance))
  const target = novel.words_per_chapter?.target ?? 420
  const summaryCap = config.context?.max_summary_words ?? 120
  const tone = novel.tone ?? 'hard-scifi'

  const slug = slugifyPremise(premise) || 'untitled'
  const hash = await configHash(config)
  const log: LogEntry[] = []
  const critiques: Critique[] = []
  const docs: Record<string, string> = {}
  // The run records what it ran with, for the same reason a terminal run does:
  // a run nobody can reconstruct the settings of is a run nobody can explain.
  docs['config.snapshot.json'] = JSON.stringify(
    { _layers: ['config/novel.config.json', `config/profiles/${profile}.json`, 'the form'],
      profile, config_hash: hash, ...config },
    null,
    2,
  )

  // Minimum calls, for the progress bar. Redrafts push the real number up.
  const total = 3 + chapters * 3 + chapters + 1
  let done = 0
  const step = (stage: string, detail: string) => {
    onProgress({ stage, detail, done, total })
  }
  const tick = () => {
    done += 1
  }

  /** Short model names live in the agent files; pricing needs full ids. */
  const modelOf = (agent: string): string => {
    const short = agents.find((a) => a.name === agent)?.model ?? ''
    if (short.includes('opus')) return 'claude-opus-5'
    if (short.includes('sonnet')) return 'claude-sonnet-5'
    if (short.includes('haiku')) return 'claude-haiku-4-5'
    return short || 'unknown'
  }

  /**
   * Characters in and characters out, for the call that just finished.
   *
   * Exact, because this page assembled the prompt and received the reply. It is
   * the one usage figure available here — `sample` returns no token counts —
   * and it is also better than what a terminal run records for the chart that
   * matters: the size of the prompt the writer was handed, rather than the
   * tokens a subagent consumed doing whatever it did.
   */
  let lastUsage = { prompt_chars: 0, output_chars: 0 }

  const ask = async (agent: string, task: string): Promise<string> => {
    if (signal?.aborted) throw new DOMException('cancelled', 'AbortError')
    const prompt = `${promptOf(agents, agent)}\n\n---\n\n${task}`
    const res = await sample(prompt, { signal })
    const text = res.text.trim()
    lastUsage = { prompt_chars: prompt.length, output_chars: text.length }
    tick()
    return text
  }

  /** Roughly four characters to a token. A rule of thumb, graded as one. */
  const CHARS_PER_TOKEN = 4
  const usage = () => ({
    ...lastUsage,
    tokens: Math.max(
      1,
      Math.round((lastUsage.prompt_chars + lastUsage.output_chars) / CHARS_PER_TOKEN),
    ),
    tokens_source: 'estimated',
  })

  const range = (r: unknown, fallback: string) => {
    const v = r as { min?: number; max?: number } | undefined
    return v?.min !== undefined ? `${v.min}–${v.max}` : fallback
  }

  // ---------------------------------------------------------- FLOW-1

  step('FLOW-1', 'the worldbuilder is writing the rules of the world')

  /**
   * The orchestrator's own check, before anything reaches a gate.
   *
   * An agent's report about itself is not evidence: in the saved run the
   * worldbuilder said it had written ~870 words and `wc -w` counted 948. So
   * the world is measured here and sent back if it misses the band or the
   * rules heading, and the rejected attempt is logged with what it cost.
   */
  const minRules = (bible.world_rules as { min?: number } | undefined)?.min ?? 4
  const minWords = (bible.world_min_words as number) ?? 400
  const maxWords = (bible.world_max_words as number) ?? 900

  const askWorld = (correction: string) =>
    ask(
      'worldbuilder',
      [
        `Premise, verbatim: ${premise}`,
        `Tone: ${tone}. Chapters: ${chapters}.`,
        `Factions: ${range(bible.factions, '2–4')}. Technology entries: ${range(bible.technology_entries, '3–6')}.`,
        `Rules under "## Rules": ${range(bible.world_rules, '4–8')}.`,
        `Length: ${minWords}–${maxWords} words.`,
        '',
        'Return the Markdown document and nothing else. Do not name any character.',
        correction,
      ]
        .filter(Boolean)
        .join('\n'),
    )

  let world = await askWorld('')
  let worldUsage = usage()
  let worldAttempt = 1

  const rulesIn = (doc: string) => {
    const section = /^##\s*Rules\s*$([\s\S]*?)(?=^##\s|$)/m.exec(doc)?.[1] ?? ''
    return section.split('\n').filter((line) => /^\s*-\s+/.test(line)).length
  }

  // Up to one correction. A second failure is accepted and left visible in the
  // log rather than looped over: the run should finish and show its scars.
  while (worldAttempt <= 2) {
    const measured = words(world)
    const rules = rulesIn(world)
    const problems = [
      measured < minWords || measured > maxWords
        ? `it is ${measured} words and the band is ${minWords}–${maxWords}`
        : '',
      rules < minRules
        ? `it has ${rules} bullets under "## Rules" and the minimum is ${minRules}`
        : '',
    ].filter(Boolean)

    if (!problems.length) break

    log.push({
      kind: 'agent_call',
      ts: now(),
      stage: 'FLOW-1',
      agent: 'worldbuilder',
      iteration: worldAttempt,
      verdict: 'rejected',
      words: measured,
      model: modelOf('worldbuilder'),
      ...worldUsage,
      reason: problems.join('; '),
    })

    if (worldAttempt === 2) break
    worldAttempt += 1
    step('FLOW-1', `the world was sent back: ${problems.join('; ')}`)
    world = await askWorld(
      `The previous attempt was rejected because ${problems.join(' and ')}. Fix that and change nothing else.`,
    )
    worldUsage = usage()
  }

  docs['bible/world.md'] = world
  log.push({
    kind: 'agent_call',
    ts: now(),
    stage: 'FLOW-1',
    agent: 'worldbuilder',
    iteration: worldAttempt,
    verdict: 'accepted',
    words: words(world),
    model: modelOf('worldbuilder'),
    ...worldUsage,
  })
  log.push({
    kind: 'stage_complete',
    ts: now(),
    stage: 'FLOW-1',
    event: 'stage_complete',
    attempts: worldAttempt,
  } as LogEntry)

  // ---------------------------------------------------------- FLOW-2

  step('FLOW-2', 'the character architect is fixing canon')
  const castRaw = await ask(
    'character-architect',
    [
      `Premise: ${premise}`,
      `Tone: ${tone}. Chapters: ${chapters}.`,
      `Characters: ${range(bible.characters, '4–7')}. Timeline rows: ${range(bible.timeline_rows, '6–12')}. Mysteries: ${range(bible.mysteries, '3–5')}.`,
      '',
      'bible/world.md, in full:',
      '',
      world,
      '',
      'Return exactly three Markdown sections separated by lines containing only',
      '"===CHARACTERS===", "===TIMELINE===" and "===MYSTERIES===", in that order,',
      'each starting with its own level-1 heading. Nothing else.',
    ].join('\n'),
  )
  const [, charactersDoc = '', timelineDoc = '', mysteriesDoc = ''] =
    /([\s\S]*?)===TIMELINE===([\s\S]*?)===MYSTERIES===([\s\S]*)$/.exec(
      castRaw.replace(/===CHARACTERS===/, ''),
    ) ?? []
  docs['bible/characters.md'] = charactersDoc.trim() || castRaw
  docs['bible/timeline.md'] = timelineDoc.trim()
  docs['bible/mysteries.md'] = mysteriesDoc.trim()

  const canonicalNames = [...docs['bible/characters.md'].matchAll(/^-\s+\*\*(.+?)\*\*/gm)].map(
    (m) => m[1]!,
  )
  log.push({
    kind: 'agent_call',
    ts: now(),
    stage: 'FLOW-2',
    agent: 'character-architect',
    iteration: 1,
    verdict: 'accepted',
    model: modelOf('character-architect'),
    ...usage(),
  })

  log.push({
    kind: 'stage_complete',
    ts: now(),
    stage: 'FLOW-2',
    event: 'stage_complete',
    characters: canonicalNames.length,
  } as LogEntry)

  const bibleBlock = [
    '### bible/world.md',
    world,
    '',
    '### bible/characters.md',
    docs['bible/characters.md'],
    '',
    '### bible/timeline.md',
    docs['bible/timeline.md'],
    '',
    '### bible/mysteries.md',
    docs['bible/mysteries.md'],
  ].join('\n')

  // ---------------------------------------------------------- FLOW-3

  step('FLOW-3', 'the plot architect is laying out the book')
  const outline = await ask(
    'plot-architect',
    [
      `Tone: ${tone}. Write exactly ${chapters} chapter entries, numbered from 1.`,
      `Promises: ${range(novel.promises, '3–5')}. Beats per chapter: ${range(novel.beats_per_chapter, '3–5')}.`,
      canonicalNames.length ? `Canonical names, spell exactly: ${canonicalNames.join(', ')}` : '',
      '',
      'Use the heading shape "### Chapter N — Title" exactly, with an em dash.',
      'The orchestrator splits your reply on it.',
      '',
      'The Story Bible:',
      '',
      bibleBlock,
    ]
      .filter(Boolean)
      .join('\n'),
  )
  docs['outline.md'] = outline
  const entries = parseOutlineEntries(outline, chapters)
  const titles = outlineTitles(outline)
  log.push({
    kind: 'agent_call',
    ts: now(),
    stage: 'FLOW-3',
    agent: 'plot-architect',
    iteration: 1,
    verdict: 'accepted',
    model: modelOf('plot-architect'),
    ...usage(),
  })

  log.push({
    kind: 'stage_complete',
    ts: now(),
    stage: 'FLOW-3',
    event: 'stage_complete',
    chapters_outlined: entries.length,
  } as LogEntry)

  // ---------------------------------------------------------- FLOW-4

  const chapterStates: RunState['chapters'] = []
  let rolling = ''

  for (let n = 1; n <= chapters; n += 1) {
    const title = titles[n - 1] ?? `Chapter ${n}`
    const entry = entries[n - 1] ?? ''
    let accepted = ''
    let acceptedScores: Record<string, number> = {}
    let drafts = 0
    const perCritic: Record<string, CritiqueIteration[]> = {
      continuity: [],
      science: [],
      length: [],
      chatter: [],
    }
    let findingsToFix: Finding[] = []
    const criticNotes: Record<string, string[]> = {}
    const repairs: Record<string, string> = {}
    /** The draft a rejection refers to. See the note below. */
    let previousDraft = ''
    /** The best draft so far, by aggregate. Not the last one. */
    let best: { draft: string; scores: Record<string, number>; aggregate: number } | null = null

    for (let iteration = 1; iteration <= maxRevisions + 1; iteration += 1) {
      drafts = iteration
      step('FLOW-4', `chapter ${n}, draft ${iteration} — the writer is working`)

      /**
       * A rejection hands back the draft it is about.
       *
       * This is not a hole in the context policy, and the distinction is the
       * whole point: the policy forbids a PREVIOUS CHAPTER's prose. This is
       * the writer's own rejected draft of the chapter it is writing now.
       * Without it the instruction "repair these findings and change nothing
       * else" is impossible — there is nothing to change — so the writer was
       * starting a brand new chapter each round, against findings that quoted
       * text no longer in it. That is why a rewrite could come back worse than
       * what it replaced.
       *
       * The last allowed draft says so, because a writer that knows it is the
       * last one spends its effort on the findings rather than on flourishes.
       */
      const last = iteration === maxRevisions + 1
      const fixes = findingsToFix.length
        ? [
            '',
            '--- YOUR PREVIOUS DRAFT, WHICH THE GATE REJECTED ---',
            previousDraft,
            '--- END OF THE REJECTED DRAFT ---',
            '',
            last
              ? `This is draft ${iteration} of ${maxRevisions + 1}, the last one allowed. Whatever you return is what ships.`
              : `That draft scored below the threshold of ${threshold}.`,
            'Return the SAME chapter with exactly these findings repaired, and change nothing else.',
            'Do not rewrite it. Do not restructure it. Each finding quotes the text it objects to:',
            ...findingsToFix.map(
              (f) => `- [${f.severity}] "${f.quote ?? ''}" — ${f.fix ?? f.claim ?? ''}`,
            ),
          ].join('\n')
        : ''

      const draftRaw = await ask(
          'chapter-writer',
          [
            `You are writing chapter ${n} of ${chapters}, titled "${title}".`,
            `Tone: ${tone}. Target ${target} words; the accepted band is ${bandMin}–${bandMax}.`,
            `Open with "# Chapter ${n} — ${title}" and then prose. Nothing before the heading.`,
            canonicalNames.length ? `Canonical names: ${canonicalNames.join(', ')}` : '',
            '',
            'The story so far — this is all you get, and it is deliberate:',
            rolling || '(nothing; this is the first chapter)',
            '',
            'Your outline entry, this chapter only:',
            entry,
            '',
            'The Story Bible:',
            '',
            bibleBlock,
            fixes,
          ]
            .filter(Boolean)
            .join('\n'),
      )
      // Captured immediately: the next `ask` overwrites the slot.
      const writerUsage = usage()
      const draft = cleanChapter(draftRaw)

      // The two arithmetic critics, run here rather than asked for.
      const measured = words(draft)
      const lengthScore = measured >= bandMin && measured <= bandMax ? 10 : 0
      const chatterScore = /^#\s+Chapter\b/.test(draft) ? 10 : 0
      perCritic.length!.push({ iteration, score: lengthScore, measured_words: measured, findings: [] })
      perCritic.chatter!.push({
        iteration,
        score: chatterScore,
        first_line: draft.split('\n')[0] ?? '',
        findings: [],
      })

      step('FLOW-4', `chapter ${n}, draft ${iteration} — two critics are reading it`)
      const criticTask = (which: 'continuity' | 'science') =>
        [
          `Judge this chapter draft. Return JSON only, no code fence:`,
          `{"score": 0-10, "findings": [{"kind": "...", "severity": "high|medium|low", "quote": "...", "fix": "...", "reference": "..."}], "notes": ["what you checked and decided not to report"]}`,
          'Include `notes` whatever the score. A 10 with no notes is indistinguishable',
          'from not having looked, and a reader is entitled to tell those apart.',
          '',
          'The draft:',
          '',
          draft,
          '',
          which === 'continuity' ? 'The Story Bible:' : 'The rules you enforce:',
          '',
          which === 'continuity' ? bibleBlock : world,
        ].join('\n')

      const criticUsage: Record<string, ReturnType<typeof usage>> = {}
      const readJson = async (which: 'continuity' | 'science') => {
        const raw = await ask(`${which}-critic`, criticTask(which))
        criticUsage[which] = usage()
        try {
          const body = /\{[\s\S]*\}/.exec(raw)?.[0] ?? raw
          const parsed = JSON.parse(body) as { score: number; findings?: Finding[]; notes?: string[] }
          return {
            score: Math.max(0, Math.min(10, parsed.score ?? 0)),
            findings: parsed.findings ?? [],
            notes: parsed.notes ?? [],
            unparsed: false as const,
          }
        } catch {
          // A critic that did not return JSON has not delivered a verdict.
          //
          // This used to return 10, which meant a malformed reply SILENTLY
          // PASSED the draft — the one failure mode a quality gate must not
          // have. There is no honest score to substitute: 10 invents an
          // approval and 0 invents a rejection. So it is reported as unscored,
          // excluded from the minimum, and surfaced as an incident. A gate
          // running on three critics instead of four is a weaker gate, and the
          // panel says which one went missing rather than pretending it agreed.
          return {
            score: null,
            findings: [],
            notes: [
              'this critic did not return JSON, so it produced no verdict; it was excluded from the aggregate rather than counted as a pass',
            ],
            unparsed: true as const,
          }
        }
      }

      // Sequential, not parallel: `lastUsage` is a single slot, and two
      // concurrent calls would each read the other's characters.
      const continuity = await readJson('continuity')
      const science = await readJson('science')
      // `-1` marks "no verdict" in the critique file, distinct from a real 0.
      perCritic.continuity!.push({
        iteration,
        score: continuity.score ?? -1,
        findings: continuity.findings,
      })
      perCritic.science!.push({ iteration, score: science.score ?? -1, findings: science.findings })
      criticNotes.continuity = [...(criticNotes.continuity ?? []), ...continuity.notes]
      criticNotes.science = [...(criticNotes.science ?? []), ...science.notes]

      for (const [critic, score] of [
        ['continuity', continuity.score],
        ['science', science.score],
      ] as const) {
        log.push({
          kind: 'agent_call',
          ts: now(),
          stage: 'FLOW-4',
          agent: `${critic}-critic`,
          chapter: n,
          iteration,
          verdict: score === null ? 'pending' : 'score',
          ...(score === null ? { reason: 'no usable verdict returned' } : { score }),
          model: modelOf(`${critic}-critic`),
          ...(criticUsage[critic] ?? {}),
        })
      }
      log.push({
        kind: 'agent_call',
        ts: now(),
        stage: 'FLOW-4',
        agent: 'chapter-writer',
        chapter: n,
        iteration,
        verdict: 'draft',
        words: measured,
        model: modelOf('chapter-writer'),
        ...writerUsage,
      })

      // A critic with no verdict is left out of the aggregate rather than
      // counted. `min` over three real scores is a weaker gate than four, and
      // that is the truth of what happened; substituting a number would not
      // make the gate stronger, only quieter.
      const scores: Record<string, number> = { length: lengthScore, chatter: chatterScore }
      if (continuity.score !== null) scores.continuity = continuity.score
      if (science.score !== null) scores.science = science.score

      const unscored = [
        continuity.score === null ? 'continuity' : '',
        science.score === null ? 'science' : '',
      ].filter(Boolean)

      const aggregate = Math.min(...Object.values(scores))
      const verdict = aggregate >= threshold ? 'accept' : last ? 'accept_with_warnings' : 'retry'

      log.push({
        kind: 'gate_decision',
        ts: now(),
        stage: 'FLOW-4',
        event: 'gate_decision',
        chapter: n,
        iteration,
        scores,
        aggregate,
        threshold,
        verdict,
        note: unscored.length
          ? `${unscored.join(' and ')} returned no usable verdict and was excluded from the minimum`
          : undefined,
      } as LogEntry)

      // The best draft, not the last.
      //
      // `on_fail: accept_with_warnings` says to keep the best one, and this
      // kept whichever came last — so a chapter whose first draft scored 7 and
      // whose third scored 4 shipped the 4. A rewrite is not guaranteed to be
      // an improvement, and the gate should not assume it was.
      if (!best || aggregate > best.aggregate) {
        best = { draft, scores, aggregate }
      }
      accepted = best.draft
      acceptedScores = best.scores

      if (verdict !== 'retry') {
        if (verdict === 'accept') {
          // An accepted draft is the one that passed, not merely the best.
          accepted = draft
          acceptedScores = scores
        }
        break
      }

      // What the writer is about to be asked to change, recorded now so the
      // panel can say it afterwards rather than leaving "not recorded".
      for (const [critic, found] of [
        ['continuity', continuity.findings],
        ['science', science.findings],
      ] as const) {
        if (!found.length) continue
        repairs[critic] =
          `draft ${iteration} was handed ${found.length} quoted finding` +
          `${found.length === 1 ? '' : 's'} from this critic` +
          (found[0]?.fix ? `, beginning: ${found[0].fix}` : '')
      }

      // Did the last repair actually land?
      //
      // A finding quotes the text it objects to, so the cheapest possible check
      // is whether that text is still there. It is arithmetic, it costs
      // nothing, and it catches the case where a writer says it fixed
      // something and did not.
      if (previousDraft) {
        const survived = findingsToFix.filter(
          (f) => f.quote && f.quote.length > 12 && draft.includes(f.quote),
        )
        if (survived.length) {
          log.push({
            kind: 'agent_call',
            ts: now(),
            stage: 'FLOW-4',
            agent: 'chapter-writer',
            chapter: n,
            iteration,
            verdict: 'rejected',
            model: modelOf('chapter-writer'),
            reason: `${survived.length} quoted passage${survived.length === 1 ? '' : 's'} the previous round asked to change ${survived.length === 1 ? 'is' : 'are'} still present verbatim`,
          })
        }
      }

      previousDraft = draft
      findingsToFix = [...continuity.findings, ...science.findings].filter(
        (f) => f.upheld !== false,
      )
      if (lengthScore === 0) {
        findingsToFix.push({
          kind: 'length',
          severity: 'high',
          quote: `${measured} words`,
          fix: `the accepted band is ${bandMin}–${bandMax} words; this draft is outside it`,
        })
      }
    }

    docs[`chapters/ch${pad(n)}.md`] = accepted
    chapterStates.push({
      n,
      status: acceptedScores && Math.min(...Object.values(acceptedScores)) >= threshold
        ? 'approved'
        : 'accepted_with_warnings',
      drafts,
      words: words(accepted),
      scores: acceptedScores,
    })

    for (const [critic, iterations] of Object.entries(perCritic)) {
      critiques.push({
        critic,
        chapter: n,
        kind: critic === 'length' || critic === 'chatter' ? 'arithmetic' : 'model',
        agent: critic === 'length' || critic === 'chatter' ? undefined : `${critic}-critic`,
        drafts,
        band:
          critic === 'length' ? { min: bandMin, max: bandMax, target } : undefined,
        rule: critic === 'chatter' ? "first line must match '# Chapter N'" : undefined,
        iterations,
        final: iterations[iterations.length - 1],
        notes: criticNotes[critic]?.length ? criticNotes[critic] : undefined,
        repair: repairs[critic],
      })
    }

    // The summary is the only channel between chapters, so it is written here
    // and capped here.
    step('FLOW-4', `chapter ${n} — writing the summary the next chapter will get`)
    const summary = await ask(
      'publisher',
      [
        `Summarise this chapter in at most ${summaryCap} words, as a record of what changed:`,
        'what happened, who now knows what, and what is still open. Prose, no heading.',
        'Return the summary and nothing else.',
        '',
        accepted,
      ].join('\n'),
    )
    const capped = summary.split(/\s+/).slice(0, summaryCap).join(' ')
    docs[`chapters/ch${pad(n)}.summary.md`] = capped
    rolling = [rolling, capped].filter(Boolean).join(' ').split(/\s+/).slice(-summaryCap).join(' ')
    docs['chapters/rolling.summary.md'] = rolling
  }

  log.push({
    kind: 'stage_complete',
    ts: now(),
    stage: 'FLOW-4',
    event: 'stage_complete',
    chapters_approved: chapterStates.filter((c) => c.status === 'approved').length,
    chapters_with_warnings: chapterStates.filter((c) => c.status !== 'approved').length,
  } as LogEntry)

  // ---------------------------------------------------------- FLOW-5

  let discarded = 0
  for (let n = 1; n <= chapters; n += 1) {
    step('FLOW-5', `chapter ${n} — the style editor is normalising presentation`)
    const before = docs[`chapters/ch${pad(n)}.md`]!
    const editedRaw = await ask(
      'style-editor',
      [
        'Normalise punctuation and spacing only. Change no word.',
        `The word count of your reply must equal ${words(before)}.`,
        'Return the chapter and nothing else.',
        '',
        before,
      ].join('\n'),
    )
    const styleUsage = usage()
    const edited = cleanChapter(editedRaw)

    // Arithmetic, not judgement: a pass that moved a word is discarded.
    const kept = words(edited) === words(before) ? edited : before
    if (kept === before && edited !== before) discarded += 1
    docs[`chapters/ch${pad(n)}.final.md`] = kept
    log.push({
      kind: 'agent_call',
      ts: now(),
      stage: 'FLOW-5',
      agent: 'style-editor',
      chapter: n,
      model: modelOf('style-editor'),
      ...styleUsage,
      verdict: kept === edited ? 'accepted' : 'rejected',
      note: kept === edited ? 'returned with the same word count' : 'word count moved; pass discarded',
    })
  }

  log.push({
    kind: 'stage_complete',
    ts: now(),
    stage: 'FLOW-5',
    event: 'stage_complete',
    passes_discarded: discarded,
  } as LogEntry)

  // ---------------------------------------------------------- FLOW-6

  step('FLOW-6', 'the publisher is writing the synopsis')
  const syn = config.outputs?.synopsis as { words?: { min: number; max: number } } | undefined
  const synopsis = await ask(
    'publisher',
    [
      `Write a back-cover synopsis, ${syn?.words?.min ?? 150}–${syn?.words?.max ?? 250} words.`,
      'Give away the first act and nothing after it. Return the synopsis and nothing else.',
      '',
      'The Story Bible and the outline:',
      '',
      bibleBlock,
      '',
      outline,
    ].join('\n'),
  )
  docs['synopsis.md'] = synopsis

  // Assembled here, in code, for the reason the procedure gives: a model asked
  // to concatenate will paraphrase a sentence the gate already approved.
  const book = [
    synopsis,
    '',
    '---',
    '',
    ...Array.from({ length: chapters }, (_, i) => docs[`chapters/ch${pad(i + 1)}.final.md`] ?? ''),
  ].join('\n\n')
  docs['dist/book.md'] = book

  log.push({
    kind: 'run_event',
    ts: now(),
    event: 'assemble',
    artefact: 'dist/book.md',
    words: words(book),
    note: 'concatenated in the page, not by an agent',
  } as LogEntry)
  log.push({
    kind: 'stage_complete',
    ts: now(),
    stage: 'FLOW-6',
    event: 'stage_complete',
  } as LogEntry)
  log.push({
    kind: 'run_event',
    ts: now(),
    event: 'run_complete',
    chapters_approved: chapterStates.filter((c) => c.status === 'approved').length,
    subagent_calls: log.filter((e) => e.kind === 'agent_call').length,
    note: 'generated in the browser through the sample capability; no tokens recorded',
  } as LogEntry)

  const manuscript = Array.from(
    { length: chapters },
    (_, i) => docs[`chapters/ch${pad(i + 1)}.final.md`] ?? '',
  ).join('\n\n')

  const state: RunState = {
    slug,
    premise,
    profile,
    config_hash: hash,
    stage: 'complete',
    chapters: chapterStates,
    style_passes_discarded: discarded,
    manuscript_words: words(manuscript),
    synopsis_words: words(synopsis),
    calls: log.filter((e) => e.kind === 'agent_call').length,
  }

  step('done', 'finished')
  return { slug, state, log, critiques, docs }
}
