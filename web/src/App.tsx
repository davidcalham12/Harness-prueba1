import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  AgentDef,
  Critique,
  FlowSpec,
  LogEntry,
  NovelConfig,
  Pricing,
  RunIndex,
  RunState,
  RunSummary,
} from './types'
import {
  PROFILE_NAMES,
  loadAgents,
  loadBaseConfig,
  loadCritiques,
  loadFlow,
  loadLog,
  loadPricing,
  loadProfile,
  loadRunIndex,
  loadState,
} from './data/load'
import { discrepancies, gateTable, summariseTokens, tokenProvenance } from './data/derive'
import { ProvenanceBadge } from './components/Provenance'
import { ContextChart } from './components/ContextChart'
import { Library } from './screens/Library'
import { NewNovel } from './screens/NewNovel'
import { Diagram } from './screens/Diagram'
import { Quality } from './screens/Quality'
import { Run } from './screens/Run'
import { Manuscript } from './screens/Manuscript'
import { Presentation } from './screens/Presentation'

/**
 * Two levels of navigation, because the panel now has two jobs.
 *
 * The Library is the front door: it lists the novels and offers to write
 * another. Everything else belongs to one run, so those screens only exist
 * once a run is open.
 */
type Place = 'library' | 'new'
type RunTab = 'diagram' | 'quality' | 'run' | 'manuscript' | 'replay'

const RUN_TABS: Array<{ id: RunTab; label: string }> = [
  { id: 'diagram', label: 'Pipeline' },
  { id: 'quality', label: 'Quality' },
  { id: 'run', label: 'Run' },
  { id: 'manuscript', label: 'Manuscript' },
  { id: 'replay', label: 'Replay' },
]

interface Shared {
  index: RunIndex | null
  flow: FlowSpec
  agents: AgentDef[]
  base: NovelConfig
  profiles: Record<string, NovelConfig>
  pricing: Pricing | null
}

export function App() {
  const [shared, setShared] = useState<Shared | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [place, setPlace] = useState<Place>('library')
  const [slug, setSlug] = useState<string | null>(null)
  const [tab, setTab] = useState<RunTab>('diagram')
  const [seed, setSeed] = useState<{ profile: string; premise: string } | null>(null)

  const [state, setState] = useState<RunState | null>(null)
  const [log, setLog] = useState<LogEntry[]>([])
  const [critiques, setCritiques] = useState<Critique[]>([])

  const [theme, setTheme] = useState<'light' | 'dark'>(
    window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
  )
  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    ;(async () => {
      try {
        const [index, flow, base, pricing] = await Promise.all([
          loadRunIndex(),
          loadFlow(),
          loadBaseConfig(),
          loadPricing(),
        ])
        // Agent names come from the flow spec plus the critics the gate names,
        // so an agent added to the pipeline appears without editing this file.
        const gateCritics = flow.stages.flatMap((s) => s.gate?.critics ?? [])
        const names = [
          ...new Set([...flow.stages.map((s) => s.agent), ...gateCritics.map((c) => `${c}-critic`)]),
        ]
        const [agents, ...profileFiles] = await Promise.all([
          loadAgents(names),
          ...PROFILE_NAMES.map((n) => loadProfile(n)),
        ])
        const profiles: Record<string, NovelConfig> = {}
        PROFILE_NAMES.forEach((name, i) => {
          const file = profileFiles[i]
          if (file) profiles[name] = file
        })
        setShared({ index, flow, agents, base, profiles, pricing })
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      }
    })()
  }, [])

  useEffect(() => {
    if (!slug) return
    ;(async () => {
      const [s, l] = await Promise.all([loadState(slug), loadLog(slug)])
      setState(s)
      setLog(l)
      const { critics, rows } = gateTable(l)
      const wanted = [...new Set(rows.map((r) => r.chapter))].flatMap((chapter) =>
        critics.map((critic) => ({ chapter, critic })),
      )
      setCritiques(await loadCritiques(slug, wanted))
    })()
  }, [slug])

  const openRun = useCallback((next: string, at: RunTab = 'diagram') => {
    setSlug(next)
    setTab(at)
  }, [])

  const duplicate = useCallback((run: RunSummary) => {
    // The premise is deliberately not carried over: duplicating a
    // configuration is for writing a different book with the same settings.
    setSeed({ profile: run.profile ?? 'tiny', premise: '' })
    setPlace('new')
  }, [])

  const tokens = useMemo(
    () => summariseTokens(log, shared?.pricing ?? null),
    [log, shared?.pricing],
  )
  const clashes = useMemo(() => discrepancies(state, log), [state, log])

  if (error) {
    return (
      <main className="boot">
        <h1>NovaForge</h1>
        <p className="check check-bad">Could not load the repository data: {error}</p>
        <p>
          The panel reads <code>specs/flow.yaml</code>, <code>config/</code> and{' '}
          <code>output/</code>. Run it with <code>npm run dev</code> from <code>web/</code>, with the
          repository checked out above it.
        </p>
      </main>
    )
  }

  if (!shared) {
    return (
      <main className="boot">
        <h1>NovaForge</h1>
        <p className="muted">loading…</p>
      </main>
    )
  }

  const inRun = slug !== null

  return (
    <div className="app">
      <header className="masthead">
        <div className="masthead-top">
          <button
            type="button"
            className="wordmark"
            onClick={() => {
              setSlug(null)
              setPlace('library')
            }}
          >
            NovaForge
          </button>

          <nav className="places">
            <button
              type="button"
              className={!inRun && place === 'library' ? 'active' : ''}
              onClick={() => {
                setSlug(null)
                setPlace('library')
              }}
            >
              Library
            </button>
            <button
              type="button"
              className={!inRun && place === 'new' ? 'active' : ''}
              onClick={() => {
                setSlug(null)
                setPlace('new')
              }}
            >
              New novel
            </button>
          </nav>

          <button
            type="button"
            className="theme"
            onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
          >
            {theme === 'dark' ? 'light' : 'dark'}
          </button>
        </div>

        {inRun && (
          <>
            <dl className="masthead-facts">
              <div>
                <dt>premise</dt>
                <dd>{state?.premise ?? <span className="muted">not recorded</span>}</dd>
              </div>
              <div>
                <dt>profile</dt>
                <dd>{state?.profile ?? <span className="muted">not recorded</span>}</dd>
              </div>
              <div>
                <dt>config</dt>
                <dd>
                  <code>{state?.config_hash ?? '—'}</code>
                </dd>
              </div>
              <div>
                <dt>stage</dt>
                <dd>{state?.stage ?? <span className="muted">in progress or unrecorded</span>}</dd>
              </div>
              <div>
                <dt>tokens</dt>
                <dd>
                  {tokens.total.toLocaleString('en-GB')}{' '}
                  <ProvenanceBadge of={tokenProvenance(tokens.sources)} compact />
                </dd>
              </div>
            </dl>

            {!state && (
              <div className="check check-warn">
                No <code>state.json</code> in this run. It is only written when a run finishes, so
                this one either stopped early or is still going. Everything below is reconstructed
                from the log.
              </div>
            )}

            {clashes.map((clash) => (
              <div key={clash.label} className="check check-warn discrepancy">
                <strong>Sources disagree on {clash.label}.</strong>
                <ul>
                  {clash.values.map((v) => (
                    <li key={v.source}>
                      <code>{v.value}</code> — {v.source}
                    </li>
                  ))}
                </ul>
                <span className="muted">
                  Shown rather than resolved. Picking one silently would be the panel deciding which
                  of its own sources to believe, which is the judgement you opened it to make.
                </span>
              </div>
            ))}

            <nav className="tabs">
              {RUN_TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={t.id === tab ? 'active' : ''}
                  onClick={() => setTab(t.id)}
                >
                  {t.label}
                </button>
              ))}
            </nav>
          </>
        )}
      </header>

      {inRun && (tab === 'quality' || tab === 'run' || tab === 'replay') && (
        <ContextChart log={log} />
      )}

      <main>
        {!inRun && place === 'library' && (
          <Library
            index={shared.index}
            pricing={shared.pricing}
            currentSlug={slug}
            onOpen={(s) => openRun(s, 'quality')}
            onRead={(s) => openRun(s, 'manuscript')}
            onDuplicate={duplicate}
            onNew={() => setPlace('new')}
          />
        )}

        {!inRun && place === 'new' && (
          <NewNovel
            base={shared.base}
            profiles={shared.profiles}
            log={log}
            pricing={shared.pricing}
            seed={seed}
            onSeedConsumed={() => setSeed(null)}
          />
        )}

        {inRun && slug && (
          <>
            {tab === 'diagram' && (
              <Diagram
                flow={shared.flow}
                log={log}
                critiques={critiques}
                onJump={(target) => setTab(target)}
              />
            )}
            {tab === 'quality' && <Quality log={log} critiques={critiques} state={state} />}
            {tab === 'run' && (
              <Run
                log={log}
                flow={shared.flow}
                agents={shared.agents}
                pricing={shared.pricing}
                critiques={critiques}
              />
            )}
            {tab === 'manuscript' && <Manuscript slug={slug} state={state} />}
            {tab === 'replay' && <Presentation log={log} />}
          </>
        )}
      </main>

      <footer className="colophon">
        Read-only. This panel reads the files the pipeline writes: it launches nothing, calls no
        model, holds no credential and writes nothing back. NovaForge itself runs in a terminal.
      </footer>
    </div>
  )
}
