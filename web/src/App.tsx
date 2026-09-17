import { useEffect, useMemo, useState } from 'react'
import type {
  AgentDef,
  Critique,
  FlowSpec,
  LogEntry,
  NovelConfig,
  Pricing,
  RunState,
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
  loadRuns,
  loadState,
} from './data/load'
import { discrepancies, gateTable, summariseTokens, tokenProvenance } from './data/derive'
import { ProvenanceBadge } from './components/Provenance'
import { ContextChart } from './components/ContextChart'
import { Quality } from './screens/Quality'
import { Run } from './screens/Run'
import { Configurator } from './screens/Configurator'
import { Manuscript } from './screens/Manuscript'
import { Presentation } from './screens/Presentation'

type Tab = 'quality' | 'run' | 'config' | 'manuscript' | 'replay'

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'quality', label: 'Quality' },
  { id: 'run', label: 'Run' },
  { id: 'config', label: 'Configurator' },
  { id: 'manuscript', label: 'Manuscript' },
  { id: 'replay', label: 'Replay' },
]

interface Loaded {
  runs: string[]
  flow: FlowSpec
  agents: AgentDef[]
  base: NovelConfig
  profiles: Record<string, NovelConfig>
  pricing: Pricing | null
}

export function App() {
  const [shared, setShared] = useState<Loaded | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [slug, setSlug] = useState<string | null>(null)
  const [state, setState] = useState<RunState | null>(null)
  const [log, setLog] = useState<LogEntry[]>([])
  const [critiques, setCritiques] = useState<Critique[]>([])
  const [tab, setTab] = useState<Tab>('quality')
  const [theme, setTheme] = useState<'light' | 'dark'>(
    window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
  )

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  // Shared, run-independent data.
  useEffect(() => {
    ;(async () => {
      try {
        const [runs, flow, base, pricing] = await Promise.all([
          loadRuns(),
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
        setShared({ runs, flow, agents, base, profiles, pricing })
        setSlug(runs[0] ?? null)
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      }
    })()
  }, [])

  // Per-run data.
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

  const tokens = useMemo(
    () => summariseTokens(log, shared?.pricing ?? null),
    [log, shared?.pricing],
  )
  const clashes = useMemo(() => discrepancies(state, log), [state, log])

  if (error) {
    return (
      <main className="boot">
        <h1>NovaForge panel</h1>
        <p className="check check-bad">Could not load the repository data: {error}</p>
        <p>
          The panel reads <code>specs/flow.yaml</code>, <code>config/</code> and{' '}
          <code>output/</code> through the dev server. Run it with <code>npm run dev</code> from{' '}
          <code>web/</code>, with the repository checked out above it.
        </p>
      </main>
    )
  }

  if (!shared) {
    return (
      <main className="boot">
        <h1>NovaForge panel</h1>
        <p className="muted">loading…</p>
      </main>
    )
  }

  if (!slug) {
    return (
      <main className="boot">
        <h1>NovaForge panel</h1>
        <div className="check check-warn">
          <strong>No runs found under <code>output/</code>.</strong>
          <p>
            Runs are not committed on this branch — <code>output/</code> is in{' '}
            <code>.gitignore</code>, because nothing here reproduces and a committed run would be a
            sample rather than something a diff could check. A fresh clone therefore has none.
          </p>
          <p>
            Produce one by invoking <code>/novaforge</code> in Claude Code from the repository root,
            then reload this page.
          </p>
        </div>
        <p className="note">
          The configurator works without a run, but its projection needs one to extrapolate from.
        </p>
      </main>
    )
  }

  return (
    <div className="app">
      <header className="masthead">
        <div className="masthead-top">
          <h1>NovaForge</h1>
          <label className="run-pick">
            run
            <select value={slug} onChange={(e) => setSlug(e.target.value)}>
              {shared.runs.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="theme" onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}>
            {theme === 'dark' ? 'light' : 'dark'}
          </button>
        </div>

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
            No <code>state.json</code> in this run. It is only written when a run finishes, so this
            one either stopped early or is still going. Everything below is reconstructed from the
            log.
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
              Shown rather than resolved. Picking one silently would be the panel deciding which of
              its own sources to believe, which is the judgement you opened it to make.
            </span>
          </div>
        ))}

        <nav className="tabs">
          {TABS.map((t) => (
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
      </header>

      {tab !== 'config' && tab !== 'manuscript' && <ContextChart log={log} />}

      <main>
        {tab === 'quality' && <Quality log={log} critiques={critiques} state={state} />}
        {tab === 'run' && (
          <Run log={log} flow={shared.flow} agents={shared.agents} pricing={shared.pricing} />
        )}
        {tab === 'config' && (
          <Configurator
            base={shared.base}
            profiles={shared.profiles}
            log={log}
            pricing={shared.pricing}
          />
        )}
        {tab === 'manuscript' && <Manuscript slug={slug} state={state} />}
        {tab === 'replay' && <Presentation log={log} />}
      </main>

      <footer className="colophon">
        Read-only. This panel reads the files the pipeline writes: it launches nothing, calls no
        model, holds no credential and writes nothing back.
      </footer>
    </div>
  )
}
