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
 * **Two runs give it two different figures, and they are not equally good.**
 *
 * A run written in this page records `prompt_chars`: the exact size of the
 * prompt the writer was handed, because the page assembled it. That is the
 * measurement this chart has always wanted.
 *
 * A run from Claude Code records the tokens a subagent consumed, which is input
 * plus output plus whatever it did internally — a proxy, and a loose one. It is
 * plotted with that said rather than omitted, because an approximate view of
 * the central claim beats no view.
 *
 * When neither figure is present the chart does not draw. A chart with no data
 * behind it is worse than an empty space, because it invites a reading.
 */
export function ContextChart({ log }: { log: LogEntry[] }) {
  const drafts = agentCalls(log)
    .filter((c) => c.agent === 'chapter-writer' && c.chapter !== undefined)
    .sort((a, b) => (a.chapter ?? 0) - (b.chapter ?? 0) || (a.iteration ?? 0) - (b.iteration ?? 0))

  // First drafts only. A redraft is handed findings as well as the Bible, so
  // its size answers a different question.
  const firsts = drafts.filter((c) => (c.iteration ?? 1) === 1)

  // Prefer the real measurement where the run has it.
  const exact = firsts.every((c) => typeof c.prompt_chars === 'number')
  const values = firsts.map((c) => (exact ? c.prompt_chars! : (c.tokens ?? 0)))
  const usable = values.filter((v) => v > 0)

  if (firsts.length < 2 || usable.length < 2) {
    return (
      <section className="context-chart">
        <h3>Context size per chapter</h3>
        <p className="muted">
          {firsts.length < 2
            ? `Needs at least two chapters to show a trend. This run has ${firsts.length}.`
            : 'Not recorded for this run.'}
        </p>
        {firsts.length >= 2 && (
          <p className="note">
            Neither the prompt size nor a token count is present on this run&rsquo;s chapter-writer
            rows, so there is nothing to plot. A run written in this page records the prompt size
            exactly; a run from Claude Code records tokens. This one has neither, and an empty space
            is the honest answer — a chart drawn from zeros would invite a reading.
          </p>
        )}
      </section>
    )
  }

  const unit = exact ? 'characters of prompt' : 'tokens consumed'
  const max = Math.max(...values)
  const min = Math.min(...values)
  const spread = max === 0 ? 0 : (max - min) / max

  const width = 560
  const height = 150
  const padX = 48
  const padY = 22
  const stepX = (width - padX * 2) / Math.max(firsts.length - 1, 1)
  const scaleY = (v: number) => height - padY - (v / max) * (height - padY * 2)

  const points = firsts.map((c, i) => ({
    x: padX + i * stepX,
    y: scaleY(values[i] ?? 0),
    chapter: c.chapter ?? i + 1,
    value: values[i] ?? 0,
  }))
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
  const short = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}k` : String(n))

  return (
    <section className="context-chart">
      <h3>Context size per chapter — the line that should be flat</h3>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Context handed to the chapter writer, first draft of each chapter, in ${unit}`}
      >
        <line x1={padX} y1={height - padY} x2={width - padX} y2={height - padY} className="axis" />
        <line x1={padX} y1={padY} x2={padX} y2={height - padY} className="axis" />
        <path d={path} className="context-line" fill="none" />
        {points.map((p) => (
          <g key={p.chapter}>
            <circle cx={p.x} cy={p.y} r={4} className="context-dot">
              <title>{`chapter ${p.chapter}: ${p.value.toLocaleString('en-GB')} ${unit}`}</title>
            </circle>
            <text x={p.x} y={height - padY + 14} textAnchor="middle" className="axis-label">
              ch{p.chapter}
            </text>
          </g>
        ))}
        <text x={padX - 6} y={scaleY(max) + 4} textAnchor="end" className="axis-label">
          {short(max)}
        </text>
        <text x={padX - 6} y={height - padY} textAnchor="end" className="axis-label">
          0
        </text>
      </svg>

      <p className={`check check-${spread < 0.25 ? 'ok' : 'warn'}`}>
        {spread < 0.25
          ? `Flat within ${(spread * 100).toFixed(0)}%. The context is not growing with the book, which is what the architecture claims.`
          : `Spread of ${(spread * 100).toFixed(0)}% between the smallest and the largest. Worth a look: this line is meant to be flat.`}
      </p>

      {exact ? (
        <p className="note">
          <strong>Measured.</strong> This run was written in this page, which assembled every prompt
          and counted it — so this is the size of what the chapter writer actually received, not a
          stand-in for it.
        </p>
      ) : (
        <p className="note">
          <strong>This is a proxy, not the measurement.</strong> The log records the tokens each
          subagent consumed, not the size of the prompt it was handed. A run written in this page
          records the prompt size exactly; recording it in Claude Code too is the one change that
          would make this chart say what it means.
        </p>
      )}
    </section>
  )
}
