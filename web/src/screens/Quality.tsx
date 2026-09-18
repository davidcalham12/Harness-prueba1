import { useMemo, useState } from 'react'
import type { AgentCall, Critique, Finding, LogEntry, RunState } from '../types'
import { agentCalls, disagreements, gateTable } from '../data/derive'
import { ProvenanceBadge } from '../components/Provenance'
import { WhyRepeated } from '../components/WhyRepeated'

/**
 * Which critics reproduce.
 *
 * Derived from the critique files' own `kind` where one is loaded, and
 * otherwise from the two the orchestrator runs in the shell. A panel that
 * painted all four scores alike would be claiming the gate is reproducible,
 * which is the one thing this branch gave up.
 */
function reproduces(critic: string, critiques: Critique[]): boolean {
  const file = critiques.find((c) => c.critic === critic)
  if (file) return file.kind === 'arithmetic'
  return critic === 'length' || critic === 'chatter'
}

function Score({
  value,
  isWorst,
  threshold,
  reproducible,
  onClick,
}: {
  value: number
  isWorst: boolean
  threshold: number
  reproducible: boolean
  onClick: () => void
}) {
  const failing = value < threshold
  return (
    <button
      type="button"
      className={`score${failing ? ' score-fail' : ''}${isWorst ? ' score-worst' : ''}`}
      onClick={onClick}
      title={
        `${value}/10 — ${reproducible ? 'arithmetic, reproduces' : 'model judgement, does not reproduce'}` +
        (isWorst ? '\nThis is the minimum, and min is what the gate uses.' : '')
      }
    >
      <span className="score-value">{value}</span>
      <span className="score-kind" aria-hidden="true">
        {reproducible ? '=' : '~'}
      </span>
      {isWorst && <span className="sr-only"> (minimum)</span>}
    </button>
  )
}

function FindingCard({ finding }: { finding: Finding }) {
  const overruled = finding.upheld === false
  return (
    <article className={`finding${overruled ? ' finding-overruled' : ''}`}>
      <header>
        <span className={`sev sev-${finding.severity}`}>{finding.severity}</span>
        <span className="finding-kind">{finding.kind}</span>
        {overruled && <span className="stamp stamp-small">overruled</span>}
      </header>
      {finding.quote && <blockquote className="quote">{finding.quote}</blockquote>}
      {finding.fix && (
        <p>
          <strong>Fix.</strong> {finding.fix}
        </p>
      )}
      {finding.claim && (
        <p>
          <strong>Claim.</strong> {finding.claim}
        </p>
      )}
      {finding.orchestrator_ruling && (
        <p className="ruling">
          <strong>Orchestrator.</strong> {finding.orchestrator_ruling}
        </p>
      )}
      {finding.reference && (
        <p className="ref">
          <a href={`#doc:${finding.reference}`}>{finding.reference}</a>
        </p>
      )}
    </article>
  )
}

/**
 * The disagreement panel.
 *
 * Two critics read the same paragraph and reached opposite verdicts; the
 * orchestrator redid the arithmetic and overruled one of them. This is what
 * distinguishes an orchestrator that arbitrates from a pipeline that obeys, and
 * it is the most informative thing the saved run produced.
 */
function Disagreement({ entry }: { entry: ReturnType<typeof disagreements>[number] }) {
  return (
    <section className="disagreement">
      <header>
        <h3>
          Chapter {entry.chapter}, draft {entry.iteration} — the critics disagreed
        </h3>
        <span className="stamp">overruled · not passed to the writer</span>
      </header>
      <p className="subject">{entry.subject}</p>
      <div className="two-up">
        <div className="position position-rejected">
          <h4>continuity-critic</h4>
          <p>{entry.continuity ?? 'no position recorded'}</p>
        </div>
        <div className="position position-upheld">
          <h4>science-critic</h4>
          <p>{entry.science ?? 'no position recorded'}</p>
        </div>
      </div>
      <div className="ruling-block">
        <h4>The orchestrator&rsquo;s ruling</h4>
        <p>{entry.orchestrator_ruling}</p>
      </div>
      <p className="note">
        On <code>main</code> this could not happen: all four critics were code. Here two are models,
        so a finding can be wrong, and passing a wrong finding back would have made the writer damage
        correct text.
      </p>
    </section>
  )
}

interface Incident {
  label: string
  count: number
  detail: string
}

/**
 * Incidents, always broken down.
 *
 * A single number would hide that these are four different kinds of thing: a
 * draft the gate rejected, a draft the orchestrator rejected before the gate
 * ever saw it, a call that produced nothing, and a limit that was exceeded
 * without blocking anything.
 */
function incidents(log: LogEntry[], critiques: Critique[]): Incident[] {
  const { rows } = gateTable(log)
  const calls = agentCalls(log)
  const out: Incident[] = []

  const retries = rows.filter((r) => r.verdict === 'retry')
  out.push({
    label: 'gate rejections',
    count: retries.length,
    detail: retries.length
      ? retries.map((r) => `ch${String(r.chapter).padStart(2, '0')} d${r.iteration} (${r.worst.join(', ')})`).join(', ')
      : 'no draft was sent back by the gate',
  })

  const preGate = calls.filter((c) => c.verdict === 'rejected')
  out.push({
    label: 'orchestrator rejections, before the gate',
    count: preGate.length,
    detail: preGate.length
      ? preGate.map((c) => `${c.agent}: ${c.reason ?? c.note ?? 'no reason recorded'}`).join(' · ')
      : 'nothing was sent back before reaching the gate',
  })

  const wasted = calls.filter(
    (c) => (c.verdict === 'rejected' || c.verdict === 'pending') && (c.tokens ?? 0) > 0,
  )
  const wastedTokens = wasted.reduce((n, c) => n + (c.tokens ?? 0), 0)
  out.push({
    label: 'calls that produced nothing',
    count: wasted.length,
    detail: wasted.length
      ? `${wastedTokens.toLocaleString('en-GB')} tokens spent for no artefact`
      : 'every call produced something',
  })

  let overruled = 0
  for (const critique of critiques) {
    for (const iteration of critique.iterations) {
      overruled += (iteration.findings ?? []).filter((f) => f.upheld === false).length
    }
  }
  out.push({
    label: 'findings overruled by the orchestrator',
    count: overruled,
    detail: overruled ? 'a critic was wrong and the orchestrator caught it' : 'every finding stood',
  })

  return out
}

export function Quality({
  log,
  critiques,
  state,
}: {
  log: LogEntry[]
  critiques: Critique[]
  state: RunState | null
}) {
  const { critics, rows } = useMemo(() => gateTable(log), [log])
  const [open, setOpen] = useState<{ chapter: number; iteration: number; critic: string } | null>(null)
  const clashes = useMemo(() => disagreements(log), [log])
  const counts = useMemo(() => incidents(log, critiques), [log, critiques])
  const calls = useMemo(() => agentCalls(log), [log])

  const openCritique = open
    ? critiques.find((c) => c.chapter === open.chapter && c.critic === open.critic)
    : undefined
  const openIteration = openCritique?.iterations.find((i) => i.iteration === open?.iteration)

  if (!rows.length) {
    return (
      <div className="empty">
        <h2>No gate decisions in this run</h2>
        <p>
          The log holds no <code>gate_decision</code> rows. Either the run stopped before FLOW-4, or
          it is still in progress.
        </p>
      </div>
    )
  }

  return (
    <div className="screen">
      <section>
        <h2>The gate</h2>
        <p className="lede">
          Four critics per draft, aggregated with <code>min</code> — a chapter is only as good as its
          worst critic. The threshold is {rows[0]!.threshold}.
        </p>
        <p className="note">
          <span className="legend-item">
            <span className="score-kind">=</span> arithmetic, reproduces
          </span>
          <span className="legend-item">
            <span className="score-kind">~</span> model judgement, does not reproduce
          </span>
          Two of the four are subagents, so the same draft can clear the gate one run and not the
          next. &ldquo;It passed the gate&rdquo; is a statement about one run, not a property of the
          text.
        </p>

        <table className="gate-table">
          <thead>
            <tr>
              <th>chapter</th>
              <th>draft</th>
              {critics.map((c) => (
                <th key={c} className={reproduces(c, critiques) ? 'col-exact' : 'col-model'}>
                  {c}
                  <span className="col-kind">{reproduces(c, critiques) ? 'arithmetic' : 'model'}</span>
                </th>
              ))}
              <th>min</th>
              <th>verdict</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.chapter}-${row.iteration}`}>
                <td>ch{String(row.chapter).padStart(2, '0')}</td>
                <td>d{row.iteration}</td>
                {critics.map((critic) => {
                  const value = row.scores[critic]
                  if (value === undefined) {
                    return (
                      <td key={critic} className="cell-absent" title="This critic did not score this draft.">
                        —
                      </td>
                    )
                  }
                  return (
                    <td key={critic}>
                      <Score
                        value={value}
                        isWorst={row.worst.includes(critic)}
                        threshold={row.threshold}
                        reproducible={reproduces(critic, critiques)}
                        onClick={() =>
                          setOpen({ chapter: row.chapter, iteration: row.iteration, critic })
                        }
                      />
                    </td>
                  )
                })}
                <td className="cell-min">{row.aggregate}</td>
                <td>
                  <span className={`verdict verdict-${row.verdict}`}>{row.verdict}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {open && (
        <section className="drawer">
          <header>
            <h3>
              ch{String(open.chapter).padStart(2, '0')} draft {open.iteration} — {open.critic}
            </h3>
            <button type="button" onClick={() => setOpen(null)} className="close">
              close
            </button>
          </header>
          {!openCritique && <p>No critique file for this critic.</p>}
          {openCritique && (
            <>
              <p className="note">
                {openCritique.kind === 'arithmetic'
                  ? 'Arithmetic the orchestrator ran in the shell. This score reproduces.'
                  : `Scored by the ${openCritique.agent ?? 'subagent'}. This score does not reproduce.`}
                {openCritique.band &&
                  ` Band ${openCritique.band.min}–${openCritique.band.max}, target ${openCritique.band.target}.`}
                {openCritique.rule && ` Rule: ${openCritique.rule}`}
              </p>
              {openIteration?.measured_words !== undefined && (
                <p>
                  Measured: <strong>{openIteration.measured_words.toLocaleString('en-GB')}</strong> words{' '}
                  <ProvenanceBadge of="measured" compact />
                </p>
              )}
              {(openIteration?.findings ?? []).length === 0 && <p>No findings on this draft.</p>}
              {(openIteration?.findings ?? []).map((f, n) => (
                <FindingCard key={n} finding={f} />
              ))}
              {openCritique.repair && (
                <p className="ruling">
                  <strong>Repair.</strong> {openCritique.repair}
                </p>
              )}
            </>
          )}
        </section>
      )}

      <WhyRepeated log={log} critiques={critiques} />

      {clashes.map((entry, n) => (
        <Disagreement key={n} entry={entry} />
      ))}

      <section>
        <h2>Incidents</h2>
        <div className="incidents">
          {counts.map((incident) => (
            <div key={incident.label} className={`incident${incident.count ? '' : ' incident-zero'}`}>
              <span className="incident-count">{incident.count}</span>
              <span className="incident-label">{incident.label}</span>
              <span className="incident-detail">{incident.detail}</span>
            </div>
          ))}
        </div>
        <p className="note">
          Not shown here because the log does not carry it: soft limits the orchestrator exceeded
          without blocking anything. In the saved run four rolling summaries went over the 120-word
          cap before being trimmed, and nothing recorded it.
        </p>
      </section>

      <section>
        <h2>Draft evolution</h2>
        <table className="plain">
          <thead>
            <tr>
              <th>chapter</th>
              <th>draft</th>
              <th>words</th>
              <th>what changed</th>
            </tr>
          </thead>
          <tbody>
            {calls
              .filter((c) => c.agent === 'chapter-writer')
              .sort((a, b) => (a.chapter ?? 0) - (b.chapter ?? 0) || (a.iteration ?? 0) - (b.iteration ?? 0))
              .map((c: AgentCall, n) => (
                <tr key={n}>
                  <td>ch{String(c.chapter ?? 0).padStart(2, '0')}</td>
                  <td>d{c.iteration}</td>
                  <td>
                    {c.words?.toLocaleString('en-GB') ?? '—'} <ProvenanceBadge of={c.words ? 'measured' : 'absent'} compact />
                  </td>
                  <td className="muted">{c.note ?? '—'}</td>
                </tr>
              ))}
          </tbody>
        </table>
        <p className="note">
          A literal diff is not possible yet: a rejected draft is not kept on disk, only the accepted
          one survives. The critique is the evidence, because it is what the gate acted on.
        </p>
      </section>

      {state && (
        <section>
          <h2>Final state</h2>
          <table className="plain">
            <thead>
              <tr>
                <th>chapter</th>
                <th>status</th>
                <th>drafts</th>
                <th>words</th>
              </tr>
            </thead>
            <tbody>
              {state.chapters.map((c) => (
                <tr key={c.n}>
                  <td>ch{String(c.n).padStart(2, '0')}</td>
                  <td>
                    <span className={`verdict verdict-${c.status === 'approved' ? 'accept' : 'accept_with_warnings'}`}>
                      {c.status}
                    </span>
                  </td>
                  <td>{c.drafts}</td>
                  <td>{c.words.toLocaleString('en-GB')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}
