import { useEffect, useMemo, useState } from 'react'
import type { LogEntry, NovelConfig, Pricing } from '../types'
import {
  deepMerge,
  deltaOf,
  deriveFromLines,
  feasibility,
  measuredPerChapter,
  nearestProfile,
  project,
  slugifyPremise,
  worstLight,
} from '../data/derive'
import { CostNote, CostTriple } from '../components/Provenance'
import { Configurator } from './Configurator'
import { devServerReason, getSampleSource, type SampleSource } from '../data/claude'
import { generateNovel, type GeneratedRun, type Progress } from '../data/generate'
import type { AgentDef, FlowSpec } from '../types'

const EXAMPLES = [
  'A deep-space salvage crew finds a derelict that remembers them',
  'The last lighthouse keeper on Titan starts receiving her own distress calls',
  'A generation ship votes on whether to wake the people who chose its course',
]

const PROFILE_BLURB: Record<string, string> = {
  tiny: 'test the whole system in minutes',
  small: 'a long short story',
  medium: 'a short novel',
  full: 'a full-length novel',
}

export function NewNovel({
  base,
  profiles,
  log,
  pricing,
  seed,
  onSeedConsumed,
  agents,
  flow,
  onGenerated,
}: {
  base: NovelConfig
  profiles: Record<string, NovelConfig>
  log: LogEntry[]
  pricing: Pricing | null
  /** A configuration carried over from "duplicate" in the Library. */
  seed: { profile: string; premise: string } | null
  onSeedConsumed: () => void
  agents: AgentDef[]
  flow: FlowSpec
  /** Hands a finished in-page run up, so the run screens can show it. */
  onGenerated: (run: GeneratedRun) => void
}) {
  const [source, setSource] = useState<SampleSource | null>(null)
  const [unavailable, setUnavailable] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [aborter, setAborter] = useState<AbortController | null>(null)

  // Resolved after the first render, never during it: a view that cannot run
  // the capability gets null and the page simply does not offer it.
  useEffect(() => {
    let live = true
    getSampleSource().then(async (found) => {
      if (!live) return
      setSource(found)
      if (!found) setUnavailable(await devServerReason())
    })
    return () => {
      live = false
    }
  }, [])
  const [premise, setPremise] = useState('')
  const [profileName, setProfileName] = useState(seed?.profile ?? 'tiny')
  const [chapters, setChapters] = useState<number | null>(null)
  const [lines, setLines] = useState<number | null>(null)
  const [advanced, setAdvanced] = useState(false)
  const [confirmed, setConfirmed] = useState(false)

  // A seed from the Library preselects the profile and deliberately leaves the
  // premise empty: the point of duplicating a configuration is to write a
  // different book with it.
  useMemo(() => {
    if (seed) {
      setProfileName(seed.profile)
      onSeedConsumed()
    }
  }, [seed, onSeedConsumed])

  const profile = profiles[profileName] ?? {}
  const withProfile = useMemo(
    () => deepMerge(base as Record<string, unknown>, profile) as NovelConfig,
    [base, profile],
  )

  const effectiveChapters = chapters ?? withProfile.novel?.chapters ?? 3
  const charsPerLine = withProfile.novel?.chars_per_line?.max ?? 64
  const profileLines = withProfile.novel?.lines_per_chapter
  const defaultLines = profileLines
    ? Math.round(((profileLines.min ?? 0) + (profileLines.max ?? 0)) / 2)
    : 60
  const effectiveLines = lines ?? defaultLines

  const derived = useMemo(
    () => deriveFromLines(effectiveLines, charsPerLine),
    [effectiveLines, charsPerLine],
  )

  /** What the simple form implies, on top of the chosen profile. */
  const simpleOverlay = useMemo(() => {
    const novel: Record<string, unknown> = {}
    if (chapters !== null) novel.chapters = chapters
    if (lines !== null) {
      novel.lines_per_chapter = derived.lines_per_chapter
      novel.words_per_chapter = derived.words_per_chapter
    }
    return Object.keys(novel).length ? { novel } : {}
  }, [chapters, lines, derived])

  const resolved = useMemo(
    () => deepMerge(withProfile as Record<string, unknown>, simpleOverlay) as NovelConfig,
    [withProfile, simpleOverlay],
  )

  const checks = useMemo(() => feasibility(resolved), [resolved])
  const light = worstLight(checks)
  const blocked = light === 'bad'

  const measured = useMemo(() => measuredPerChapter(log), [log])
  const maxRevisions = resolved.quality_gate?.max_revisions ?? 2
  const projection = useMemo(
    () =>
      project(
        effectiveChapters,
        maxRevisions,
        { writer: measured.writer, critics: measured.critics, style: measured.style },
        measured.setup,
        pricing,
      ),
    [effectiveChapters, maxRevisions, measured, pricing],
  )

  const budget = resolved.budget ?? {}
  const overCalls = budget.max_calls !== undefined && projection.maxCalls > budget.max_calls
  const overCost = budget.max_cost_usd !== undefined && projection.maxCost.high > budget.max_cost_usd

  const nearest = nearestProfile(effectiveChapters, profiles)
  const offProfile = nearest && profiles[nearest]?.novel?.chapters !== effectiveChapters

  const delta = useMemo(
    () => (deltaOf(base, resolved) as Record<string, unknown> | undefined) ?? {},
    [base, resolved],
  )
  const deltaJson = JSON.stringify(delta, null, 2)
  const slug = premise ? slugifyPremise(premise) : '<derived from the premise>'
  const command = `/novaforge\n  premise: ${premise || '<your premise>'}\n  profile: ${profileName}`

  const download = () => {
    const blob = new Blob([deltaJson], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${slug || profileName}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const run = async () => {
    if (!source) return
    const controller = new AbortController()
    setAborter(controller)
    setRunning(true)
    setFailure(null)
    setProgress({ stage: 'starting', detail: 'asking Claude for the world', done: 0, total: 1 })
    try {
      const generated = await generateNovel({
        premise: premise.trim(),
        config: resolved,
        profile: profileName,
        agents,
        flow,
        sample: source.sample,
        signal: controller.signal,
        onProgress: setProgress,
      })
      onGenerated(generated)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setFailure(message.includes('cancelled') || message.includes('abort') ? 'Stopped.' : message)
    } finally {
      setRunning(false)
      setAborter(null)
    }
  }

  if (running || failure) {
    const pct = progress ? Math.min(100, Math.round((progress.done / progress.total) * 100)) : 0
    return (
      <div className="screen">
        <section className="running">
          <h2>{failure ? 'It stopped' : 'Writing'}</h2>
          {failure ? (
            <>
              <p className="check check-bad">{failure}</p>
              <button type="button" onClick={() => setFailure(null)}>
                Back to the form
              </button>
            </>
          ) : (
            <>
              <p className="lede">
                {progress?.detail ?? 'starting'}
              </p>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${pct}%` }} />
              </div>
              <p className="progress-meta">
                <strong>{progress?.stage}</strong> · {progress?.done ?? 0} of about{' '}
                {progress?.total ?? '?'} calls
              </p>
              <p className="note">
                Each stage is a real request to Claude, paid by whoever has this page open. The
                chapter writer is never sent a previous chapter&rsquo;s prose — only the Story Bible,
                its own outline entry and the capped rolling summary.
              </p>
              <button type="button" onClick={() => aborter?.abort()}>
                Stop
              </button>
            </>
          )}
        </section>
      </div>
    )
  }

  if (confirmed) {
    return (
      <div className="screen">
        <section className="handoff">
          <h2>Ready to run</h2>
          <p className="lede">
            NovaForge runs in your terminal. Copy this command and paste it into Claude Code; the
            novel appears in the Library when it finishes.
          </p>

          <h3>1 · the command</h3>
          <pre className="code">{command}</pre>
          <button type="button" onClick={() => navigator.clipboard?.writeText(command)}>
            Copy the command
          </button>

          <h3>2 · the profile, if you changed anything</h3>
          <pre className="code">
            {deltaJson === '{}' ? '{}  // identical to the shipped base' : deltaJson}
          </pre>
          <button type="button" onClick={download}>
            Download {slug || profileName}.json
          </button>
          <p className="note">
            Only the delta against the base, which is exactly what a profile file is. If the download
            does nothing, you are on the published page — the viewer blocks downloads a page starts
            itself. Copy the JSON above instead.
          </p>

          <h3>3 · where it will appear</h3>
          <p>
            In <code>output/{slug}/</code>. Run <code>npm run index:runs</code> afterwards and it
            shows up in the Library.
          </p>

          <button type="button" onClick={() => setConfirmed(false)}>
            Back to the form
          </button>
        </section>
      </div>
    )
  }

  return (
    <div className="screen">
      <section>
        <h2>Write a novel</h2>
        <p className="lede">
          Eight agents, six stages, and a quality gate that sends chapters back. Three questions is
          all it takes to start.
        </p>

        <div className="ask">
          <label htmlFor="premise">
            <span className="ask-number">1</span> What should it be about?
          </label>
          <textarea
            id="premise"
            rows={2}
            value={premise}
            placeholder="One or two sentences."
            onChange={(e) => setPremise(e.target.value)}
          />
          <div className="examples">
            {EXAMPLES.map((example) => (
              <button key={example} type="button" className="example" onClick={() => setPremise(example)}>
                {example}
              </button>
            ))}
          </div>
          <p className="note note-tight">
            The premise is not a config field. It is an argument to the procedure, recorded in{' '}
            <code>state.json</code> as <code>premise</code>, and it goes in the command rather than
            in the profile JSON.
          </p>
        </div>

        <div className="ask">
          <label htmlFor="chapters">
            <span className="ask-number">2</span> How many chapters?
          </label>
          <div className="profile-cards">
            {Object.entries(profiles).map(([name, config]) => (
              <button
                key={name}
                type="button"
                className={`profile-card${name === profileName ? ' active' : ''}`}
                onClick={() => {
                  setProfileName(name)
                  setChapters(null)
                  setLines(null)
                }}
              >
                <span className="profile-name">{name}</span>
                <span className="profile-chapters">{config.novel?.chapters ?? '—'} chapters</span>
                <span className="profile-words">
                  {config.novel?.words_per_chapter?.target
                    ? `~${config.novel.words_per_chapter.target} words each`
                    : ''}
                </span>
                <span className="profile-blurb">{PROFILE_BLURB[name]}</span>
              </button>
            ))}
          </div>
          <input
            id="chapters"
            type="number"
            min={1}
            max={200}
            value={chapters ?? effectiveChapters}
            onChange={(e) => setChapters(Number(e.target.value) || null)}
          />
          {offProfile && (
            <p className="note note-tight">
              Starting from <strong>{nearest}</strong>, with {effectiveChapters} chapters.
            </p>
          )}
        </div>

        <div className="ask">
          <label htmlFor="lines">
            <span className="ask-number">3</span> Roughly how many lines per chapter?
          </label>
          <input
            id="lines"
            type="number"
            min={5}
            max={800}
            value={lines ?? effectiveLines}
            onChange={(e) => setLines(Number(e.target.value) || null)}
          />
          <p className="note note-tight">
            Becomes a line band of {derived.lines_per_chapter.min}–{derived.lines_per_chapter.max} and
            a target of {derived.words_per_chapter.target} words ({derived.words_per_chapter.min}–
            {derived.words_per_chapter.max}). The pipeline gates on words; this is the bridge, and it
            is approximate — within 8% of both shipped profiles, well inside the{' '}
            {resolved.novel?.tolerance_pct ?? 20}% tolerance.
          </p>
        </div>

        <details className="advanced" open={advanced} onToggle={(e) => setAdvanced(e.currentTarget.open)}>
          <summary>Everything else</summary>
          <p className="note">
            The full three-layer view. Anything you set here wins over the three questions above, and
            is not recalculated when you change them.
          </p>
          {advanced && (
            <Configurator base={base} profiles={profiles} log={log} pricing={pricing} embedded />
          )}
        </details>
      </section>

      <section className="before-you-run">
        <h2>
          Before you run it <span className={`light light-${light}`}>{light}</span>
        </h2>

        <ul className="checks">
          {checks.map((check, n) => (
            <li key={n} className={`check check-${check.light}`}>
              <strong>{check.label}</strong> — {check.detail}
            </li>
          ))}
        </ul>

        <table className="plain">
          <tbody>
            <tr>
              <th>subagent calls</th>
              <td className={overCalls ? 'over' : ''}>
                {projection.minCalls}–{projection.maxCalls}
                {budget.max_calls !== undefined && (
                  <span className="muted"> · ceiling {budget.max_calls}</span>
                )}
              </td>
            </tr>
            <tr>
              <th>tokens</th>
              <td>
                {Math.round(projection.minTokens).toLocaleString('en-GB')}–
                {Math.round(projection.maxTokens).toLocaleString('en-GB')}
              </td>
            </tr>
            <tr>
              <th>cost, best case</th>
              <td>
                <CostTriple cost={projection.minCost} />
              </td>
            </tr>
            <tr>
              <th>cost, worst case</th>
              <td className={overCost ? 'over' : ''}>
                <CostTriple cost={projection.maxCost} />
              </td>
            </tr>
            <tr>
              <th>time</th>
              <td>
                <span className="muted">not predictable.</span> The saved three-chapter run took
                about 37 minutes of wall clock, but durations are not recorded per call, so that is
                one measurement rather than an estimate.
              </td>
            </tr>
          </tbody>
        </table>

        <CostNote share={pricing?.assumed_input_share} />

        <p className="warn-block">
          <strong>Nothing stops a run once it starts.</strong> The <code>budget</code> block is
          advisory on this branch — no ceiling is checked before a call. This screen is the control,
          and it runs once, here.
        </p>

        <div className="run-actions">
          {source && (
            <button
              type="button"
              className="primary"
              disabled={blocked || !premise.trim()}
              onClick={run}
            >
              {blocked
                ? 'Fix the configuration first'
                : !premise.trim()
                  ? 'Write a premise first'
                  : 'Write it here'}
            </button>
          )}
          <button
            type="button"
            className={source ? '' : 'primary'}
            disabled={blocked || !premise.trim()}
            onClick={() => setConfirmed(true)}
          >
            Get the command instead
          </button>
        </div>

        {source ? (
          <div className="check check-warn">
            <strong>Writing it here runs the pipeline in this page.</strong>{' '}
            {source.kind === 'claude-code'
              ? 'Each agent runs through Claude Code on this machine, billed to its session.'
              : source.kind === 'artifact'
                ? 'Every stage is a request to Claude, billed to whoever has the page open, and the first one asks your permission.'
                : 'Every stage goes to the Anthropic API through the dev server, with the credential it holds.'} The result is held in memory: it is shown on the same screens as a saved run
            and it is gone when you reload. Two things differ from a terminal run, and they are worth
            knowing —{' '}
            <strong>the agents are prompts here rather than subagents</strong>, so the chapter
            writer&rsquo;s isolation rests on this page not sending it prior prose rather than on it
            having no tool to fetch any; and{' '}
            {source.kind === 'claude-code' ? (
              <>
                <strong>Claude Code reports what each call cost</strong>, so this run states one
                dollar figure instead of bounding an estimate
              </>
            ) : source.reportsUsage ? (
              <>
                <strong>token counts come back real</strong>, so this run reports measured usage
                rather than an estimate
              </>
            ) : (
              <>
                <strong>no token counts come back</strong>, so tokens are estimated from the
                characters this page sends and receives
              </>
            )}
            .
          </div>
        ) : unavailable ? (
          <div className="check check-warn">
            <strong>This page could write the novel here, and cannot yet.</strong> {unavailable}
            <p className="note">
              In PowerShell, from the repository root:
              <br />
              <code>$env:ANTHROPIC_API_KEY = 'sk-ant-…'</code>
              <br />
              then restart <code>npm run dev</code>. The key stays in the dev server process — the
              browser never receives it, and it is never part of a build.
              <br />
              <br />
              Or, with <strong>no key at all</strong>: put the <code>claude</code> CLI on this dev
              server&rsquo;s PATH. Each agent then runs through your own Claude Code session, as a
              real subagent with its real tools. Meanwhile the command below runs the same pipeline
              in your terminal.
            </p>
          </div>
        ) : (
          <p className="note">
            NovaForge runs in your terminal. This screen hands you a command and a profile; it starts
            nothing, calls no model and writes nothing. (On the published page, and on a dev server
            holding a credential, it can also write the novel here.)
          </p>
        )}
      </section>
    </div>
  )
}
