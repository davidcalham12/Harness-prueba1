import { useEffect, useMemo, useRef, useState } from 'react'
import type { LogEntry } from '../types'

/** One line of narration per log row, in the language of what happened. */
function narrate(entry: LogEntry): { title: string; detail: string; tone: string } {
  switch (entry.kind) {
    case 'agent_call': {
      const where = entry.chapter ? ` · chapter ${entry.chapter}, draft ${entry.iteration ?? 1}` : ''
      return {
        title: `${entry.stage ?? ''} ${entry.agent}${where}`.trim(),
        detail:
          entry.note ??
          entry.reason ??
          [
            entry.verdict && `verdict ${entry.verdict}`,
            entry.words !== undefined && `${entry.words.toLocaleString('en-GB')} words`,
            entry.score !== undefined && `score ${entry.score}/10`,
            entry.tokens && `${entry.tokens.toLocaleString('en-GB')} tokens`,
          ]
            .filter(Boolean)
            .join(' · '),
        tone: entry.verdict === 'rejected' ? 'bad' : 'normal',
      }
    }
    case 'gate_decision': {
      const scores = Object.entries(entry.scores)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([k, v]) => `${k} ${v}`)
        .join(', ')
      return {
        title: `gate · chapter ${entry.chapter}, draft ${entry.iteration} → ${entry.verdict.toUpperCase()}`,
        detail: `${scores} · min ${entry.aggregate}, threshold ${entry.threshold}`,
        tone: entry.verdict === 'retry' ? 'bad' : 'good',
      }
    }
    case 'critic_disagreement':
      return {
        title: `the critics disagreed · chapter ${entry.chapter}`,
        detail: `${entry.subject} — ${entry.orchestrator_ruling}`,
        tone: 'clash',
      }
    case 'stage_complete':
      return {
        title: `${entry.stage ?? 'stage'} complete`,
        detail: Object.entries(entry)
          .filter(([k]) => !['kind', 'ts', 'stage', 'event', 'config_hash'].includes(k))
          .map(([k, v]) => `${k}: ${String(v)}`)
          .join(' · '),
        tone: 'good',
      }
    default:
      return {
        title: String((entry as { event?: string }).event ?? 'event'),
        detail: Object.entries(entry)
          .filter(([k]) => !['kind', 'ts', 'event', 'config_hash'].includes(k))
          .map(([k, v]) => `${k}: ${String(v)}`)
          .join(' · '),
        tone: 'normal',
      }
  }
}

/**
 * Replays the saved run, step by step.
 *
 * Reads the log that already exists, so it costs nothing and risks nothing.
 * This is what the project gets demonstrated with: the whole system, including
 * a rejection and an overruled critic, without spending a token.
 */
export function Presentation({ log }: { log: LogEntry[] }) {
  const steps = useMemo(() => log.map((entry) => ({ entry, ...narrate(entry) })), [log])
  const [at, setAt] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1200)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!playing) return
    if (at >= steps.length) {
      setPlaying(false)
      return
    }
    const timer = setTimeout(() => setAt((n) => n + 1), speed)
    return () => clearTimeout(timer)
  }, [playing, at, speed, steps.length])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [at])

  return (
    <div className="screen presentation">
      <section>
        <h2>Replay</h2>
        <p className="lede">
          Steps through the saved log. Reads only; nothing is launched and no token is spent.
        </p>
        <div className="controls">
          <button type="button" onClick={() => setPlaying((p) => !p)}>
            {playing ? 'pause' : at >= steps.length ? 'replay' : 'play'}
          </button>
          <button
            type="button"
            onClick={() => {
              setPlaying(false)
              setAt(0)
            }}
          >
            reset
          </button>
          <button type="button" onClick={() => setAt((n) => Math.min(n + 1, steps.length))}>
            step
          </button>
          <button type="button" onClick={() => setAt(steps.length)}>
            show all
          </button>
          <label>
            speed
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
              <option value={2400}>slow</option>
              <option value={1200}>normal</option>
              <option value={500}>fast</option>
              <option value={120}>very fast</option>
            </select>
          </label>
          <span className="muted">
            {Math.min(at, steps.length)} / {steps.length}
          </span>
        </div>

        <ol className="replay">
          {steps.slice(0, at).map((step, n) => (
            <li key={n} className={`replay-step tone-${step.tone}`}>
              <span className="replay-index">{n + 1}</span>
              <div>
                <strong>{step.title}</strong>
                {step.detail && <p>{step.detail}</p>}
              </div>
            </li>
          ))}
        </ol>
        <div ref={endRef} />
        {at === 0 && <p className="muted">Press play.</p>}
      </section>
    </div>
  )
}
