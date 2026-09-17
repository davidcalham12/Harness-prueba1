import type { LogEntry } from '../types'
import { agentCalls } from '../data/derive'

/**
 * The line that should be flat.
 *
 * This is the thesis of the whole project: the chapter writer never receives a
 * previous chapter's prose, so the prompt for chapter 34 is the same size as
 * the prompt for chapter 1. If that line ever climbs, the guarantee has broken
 * and this chart is where it shows.
 *
 * **What is plotted is not what should be plotted.** The log records the tokens
 * a subagent consumed, which is input plus output plus whatever the agent did
 * internally — not the size of the prompt it was handed. It is a proxy, and a
 * loose one. The honest version needs the orchestrator to record the assembled
 * prompt size, which it does not do yet. Plotted with the caveat rather than
 * omitted, because an approximate view of the central claim beats no view.
 */
export function ContextChart({ log }: { log: LogEntry[] }) {
  const drafts = agentCalls(log)
    .filter((c) => c.agent === 'chapter-writer' && c.chapter !== undefined)
    .sort((a, b) => (a.chapter ?? 0) - (b.chapter ?? 0) || (a.iteration ?? 0) - (b.iteration ?? 0))

  // First drafts only. A redraft is handed findings as well as the Bible, so
  // its token count answers a different question.
  const firsts = drafts.filter((c) => (c.iteration ?? 1) === 1)

  if (firsts.length < 2) {
    return (
      <section className="context-chart">
        <h3>Context size per chapter</h3>
        <p className="muted">
          Needs at least two chapters to show a trend. This run has {firsts.length}.
        </p>
      </section>
    )
  }

  const values = firsts.map((c) => c.tokens ?? 0)
  const max = Math.max(...values, 1)
  const min = Math.min(...values)
  const spread = max === 0 ? 0 : (max - min) / max

  const width = 560
  const height = 150
  const padX = 42
  const padY = 22
  const stepX = (width - padX * 2) / Math.max(firsts.length - 1, 1)
  const scaleY = (v: number) => height - padY - (v / max) * (height - padY * 2)

  const points = firsts.map((c, i) => ({
    x: padX + i * stepX,
    y: scaleY(c.tokens ?? 0),
    chapter: c.chapter ?? i + 1,
    tokens: c.tokens ?? 0,
  }))
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')

  return (
    <section className="context-chart">
      <h3>Context size per chapter — the line that should be flat</h3>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Tokens consumed by the chapter writer, first draft of each chapter">
        <line x1={padX} y1={height - padY} x2={width - padX} y2={height - padY} className="axis" />
        <line x1={padX} y1={padY} x2={padX} y2={height - padY} className="axis" />
        <path d={path} className="context-line" fill="none" />
        {points.map((p) => (
          <g key={p.chapter}>
            <circle cx={p.x} cy={p.y} r={4} className="context-dot">
              <title>{`chapter ${p.chapter}: ${p.tokens.toLocaleString('en-GB')} tokens`}</title>
            </circle>
            <text x={p.x} y={height - padY + 14} textAnchor="middle" className="axis-label">
              ch{p.chapter}
            </text>
          </g>
        ))}
        <text x={padX - 6} y={scaleY(max)} textAnchor="end" className="axis-label">
          {(max / 1000).toFixed(0)}k
        </text>
      </svg>

      <p className={`check check-${spread < 0.25 ? 'ok' : 'warn'}`}>
        {spread < 0.25
          ? `Flat within ${(spread * 100).toFixed(0)}%. The prompt is not growing with the book, which is what the architecture claims.`
          : `Spread of ${(spread * 100).toFixed(0)}% between the smallest and largest. Worth a look: this line is meant to be flat.`}
      </p>
      <p className="note">
        <strong>This is a proxy, not the measurement.</strong> The log records the tokens each
        subagent consumed, not the size of the prompt it was handed. The real figure needs the
        orchestrator to record the assembled prompt size, which it does not do yet — the place for it
        is here, ready.
      </p>
    </section>
  )
}
