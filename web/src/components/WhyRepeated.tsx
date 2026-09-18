import { useMemo, useState } from 'react'
import type { AgentCall, Critique, Finding, LogEntry } from '../types'
import { agentCalls, disagreements, gateTable, runLocally } from '../data/derive'

/**
 * Why a chapter was written twice, in the words a reader already has.
 *
 * Everything here comes out of a field: the scores from `gate_decision`, the
 * quote and the explanation from a finding, what changed from the critique's
 * `repair` and the log's `note`. Nothing is paraphrased and nothing is
 * summarised — the explanations were written in plain language already, and
 * rewriting them would put a second author between the reader and the record.
 *
 * The one thing this component does add is the framing: that a rewrite is the
 * system working rather than a fault, and that the gate takes the *minimum* of
 * four scores, which is why a single 7 sends back a draft three critics liked.
 */

const CRITIC_LABEL: Record<string, string> = {
  continuity: 'continuity',
  science: 'science',
  length: 'length',
  chatter: 'opening',
}

/** Finding kinds as they appear in the data, in words. */
const KIND_LABEL: Record<string, string> = {
  'timeline-math': 'timeline arithmetic',
  'rule-shorthand': 'how a rule was used',
  'physics-violation': 'physical inconsistency',
  'character-status': 'a character’s status',
  'name-drift': 'a name drifted from canon',
  arithmetic: 'arithmetic',
}

const SEVERITY_LABEL: Record<string, string> = {
  high: 'high',
  medium: 'medium',
  low: 'low',
}

function FindingCard({ finding }: { finding: Finding }) {
  const [open, setOpen] = useState(false)
  const overruled = finding.upheld === false

  return (
    <article className={`why-finding${overruled ? ' why-overruled' : ''}`}>
      <header>
        <span className={`sev sev-${finding.severity}`}>
          {SEVERITY_LABEL[finding.severity] ?? finding.severity}
        </span>
        <span className="why-kind">{KIND_LABEL[finding.kind] ?? finding.kind}</span>
        {overruled && <span className="stamp stamp-small">overruled by the orchestrator</span>}
      </header>

      {finding.quote && (
        <blockquote className="quote" lang="en">
          {finding.quote}
        </blockquote>
      )}

      {finding.fix && <p>{finding.fix}</p>}
      {finding.claim && <p>{finding.claim}</p>}

      {finding.reference && (
        <p className="ref">
          checked against <a href={`#doc:${finding.reference}`}>{finding.reference}</a>
        </p>
      )}

      {overruled && finding.orchestrator_ruling && (
        <>
          <button type="button" className="link" onClick={() => setOpen((v) => !v)}>
            {open ? 'hide' : 'why it was overruled'}
          </button>
          {open && <p className="ruling">{finding.orchestrator_ruling}</p>}
        </>
      )}
    </article>
  )
}

/** What a critic checked and decided not to report. */
function WhatWasChecked({ notes }: { notes: string[] }) {
  const [open, setOpen] = useState(false)
  if (!notes.length) return null
  return (
    <div className="checked">
      <button type="button" className="link" onClick={() => setOpen((v) => !v)}>
        {open ? 'hide what was checked' : `what was checked (${notes.length})`}
      </button>
      {open && (
        <ul>
          {notes.map((note, n) => (
            <li key={n} lang="en">
              {note}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function WhyRepeated({
  log,
  critiques,
}: {
  log: LogEntry[]
  critiques: Critique[]
}) {
  const { rows } = useMemo(() => gateTable(log), [log])
  const calls = useMemo(() => agentCalls(log), [log])
  const clashes = useMemo(() => disagreements(log), [log])

  const rejected = rows.filter((r) => r.verdict === 'retry')
  const cleanFirstTime = rows.filter((r) => r.iteration === 1 && r.verdict === 'accept')

  const draftWords = (chapter: number, iteration: number) =>
    calls.find(
      (c: AgentCall) =>
        c.agent === 'chapter-writer' && c.chapter === chapter && (c.iteration ?? 1) === iteration,
    )

  return (
    <section>
      <h2>Why a chapter was written twice</h2>
      <p className="lede">
        A chapter is sent back when the <strong>worst</strong> of its four scores falls below the
        threshold — the scores aggregate with <code>min</code>, so one 7 outweighs three 10s. Being
        sent back is the system working, not a fault.
      </p>

      {rejected.length === 0 && (
        <p className="muted">No draft was sent back in this run.</p>
      )}

      {rejected.map((row) => {
        const failing = Object.entries(row.scores)
          .filter(([, v]) => v < row.threshold)
          .map(([k]) => k)
        const clash = clashes.find(
          (c) => c.chapter === row.chapter && c.iteration === row.iteration,
        )

        // Findings actually handed back, versus findings raised. The
        // difference is the orchestrator's arbitration and it belongs in the
        // headline, not in a footnote.
        const forThisDraft = critiques
          .filter((c) => c.chapter === row.chapter)
          .map((c) => ({
            critique: c,
            iteration: c.iterations.find((i) => i.iteration === row.iteration),
          }))
          .filter((c) => c.iteration)

        const raised = forThisDraft.reduce(
          (n, c) => n + (c.iteration?.findings?.length ?? 0),
          0,
        )
        const passed = forThisDraft.reduce(
          (n, c) => n + (c.iteration?.findings?.filter((f) => f.upheld !== false).length ?? 0),
          0,
        )

        const next = rows.find(
          (r) => r.chapter === row.chapter && r.iteration === row.iteration + 1,
        )
        const before = draftWords(row.chapter, row.iteration)
        const after = draftWords(row.chapter, row.iteration + 1)

        return (
          <article key={`${row.chapter}-${row.iteration}`} className="why-block">
            <header>
              <h3>
                Chapter {row.chapter}, draft {row.iteration} — rewritten
              </h3>
              <span className="why-scores">
                {Object.entries(row.scores)
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([critic, value]) => (
                    <span key={critic} className={value < row.threshold ? 'why-score fail' : 'why-score'}>
                      {CRITIC_LABEL[critic] ?? critic} {value}
                    </span>
                  ))}
              </span>
            </header>

            <p className="why-headline">
              {failing.length === 1 ? (
                <>
                  The <strong>{CRITIC_LABEL[failing[0]!] ?? failing[0]}</strong> critic scored{' '}
                  {row.scores[failing[0]!]} out of 10, and the minimum is {row.threshold}.
                </>
              ) : (
                <>
                  {failing.length} critics scored below {row.threshold}, and the lowest was{' '}
                  {row.aggregate}.
                </>
              )}{' '}
              {raised === passed ? (
                <>
                  {raised} problem{raised === 1 ? ' was' : 's were'} found.
                </>
              ) : (
                <>
                  {raised} problems were raised, but only <strong>{passed}</strong> reached the
                  writer: the {raised - passed === 1 ? 'other was' : 'others were'} checked and found
                  to be wrong.
                </>
              )}
            </p>

            {forThisDraft.map(({ critique, iteration }) => {
              const findings = iteration?.findings ?? []
              if (!findings.length) return null
              return (
                <div key={critique.critic} className="why-critic">
                  <h4>
                    {CRITIC_LABEL[critique.critic] ?? critique.critic} — {iteration?.score}/10,{' '}
                    {findings.length} problem{findings.length === 1 ? '' : 's'}
                    <span className="why-who">
                      {runLocally(critique.critic, critiques)
                        ? 'run by the orchestrator'
                        : 'a subagent'}
                    </span>
                  </h4>
                  {findings.map((finding, n) => (
                    <FindingCard key={n} finding={finding} />
                  ))}
                </div>
              )
            })}

            {clash && (
              <p className="why-clash">
                The two critics disagreed about this draft, and the orchestrator ruled. See the
                disagreement panel below.
              </p>
            )}

            <div className="why-changed">
              <h4>What changed</h4>
              {forThisDraft
                .filter(({ critique }) => critique.repair)
                .map(({ critique }) => (
                  <p key={critique.critic}>
                    <strong>{CRITIC_LABEL[critique.critic] ?? critique.critic}</strong> —{' '}
                    <span lang="en">{critique.repair}</span>
                  </p>
                ))}
              {forThisDraft.every(({ critique }) => !critique.repair) && (
                <p className="muted">The critique files do not record what was changed.</p>
              )}
              <p className="why-delta">
                {before?.words !== undefined && after?.words !== undefined && (
                  <>
                    {before.words} → {after.words} words.{' '}
                  </>
                )}
                {after?.note && <span lang="en">{after.note}.</span>}
              </p>
            </div>

            {next && (
              <p className={`why-result why-result-${next.verdict}`}>
                <strong>Draft {next.iteration} — {next.verdict === 'accept' ? 'accepted' : next.verdict}.</strong>{' '}
                Lowest score {next.aggregate}, {next.aggregate >= next.threshold ? 'above' : 'below'}{' '}
                the minimum of {next.threshold}.
              </p>
            )}
          </article>
        )
      })}

      {cleanFirstTime.length > 0 && (
        <div className="why-clean">
          <h3>And the ones that passed first time</h3>
          <p className="lede">
            A 10 out of 10 should not be a black box. The critics record what they looked at and
            decided not to report.
          </p>
          {cleanFirstTime.map((row) => {
            const notes = critiques
              .filter((c) => c.chapter === row.chapter && c.notes?.length)
              .flatMap((c) => (c.notes ?? []).map((note) => `${CRITIC_LABEL[c.critic] ?? c.critic}: ${note}`))
            return (
              <div key={row.chapter} className="why-clean-row">
                <strong>Chapter {row.chapter}</strong> — accepted on the first draft, lowest score{' '}
                {row.aggregate}.
                <WhatWasChecked notes={notes} />
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
