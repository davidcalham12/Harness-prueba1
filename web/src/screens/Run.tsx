import { useMemo } from 'react'
import type { AgentCall, AgentDef, FlowSpec, LogEntry, Pricing } from '../types'
import { agentCalls, costOf, summariseTokens, tokenProvenance } from '../data/derive'
import { CostNote, CostTriple, ProvenanceBadge } from '../components/Provenance'

/**
 * The note a tool list deserves.
 *
 * The tools column is the security model of this system, not a technical
 * detail, so the panel explains the two that carry weight rather than printing
 * them as labels among labels.
 */
function toolNote(agent: AgentDef): string | null {
  if (agent.name === 'chapter-writer') {
    return 'Glob returns file paths and cannot return contents, so a previous chapter is unreachable to this agent even deliberately. It is arithmetic, not a promise.'
  }
  if (agent.tools.includes('Write')) {
    return 'One of the two agents permitted to write the Story Bible.'
  }
  if (agent.tools.length === 0) {
    return 'No tools declared in the front matter, which means this agent inherits the default set rather than having none.'
  }
  return null
}

function AgentCard({
  call,
  def,
  pricing,
}: {
  call: AgentCall
  def: AgentDef | undefined
  pricing: Pricing | null
}) {
  const cost = costOf(call.tokens ?? 0, call.model, pricing)
  const note = def ? toolNote(def) : null
  const heavy = call.model?.includes('opus')

  return (
    <article className={`agent-card${call.verdict === 'rejected' ? ' agent-card-bad' : ''}`}>
      <header>
        <span className="agent-name">{call.agent}</span>
        {call.model && (
          <span className={`model${heavy ? ' model-heavy' : ''}`} title={heavy ? 'Opus: 2.5× the price of Sonnet per token.' : 'Sonnet'}>
            {call.model.replace('claude-', '')}
          </span>
        )}
        {call.verdict && <span className={`verdict verdict-${call.verdict}`}>{call.verdict}</span>}
      </header>

      {def && def.tools.length > 0 && (
        <p className="tools">
          {def.tools.map((t) => (
            <span key={t} className={`tool tool-${t.toLowerCase()}`}>
              {t}
            </span>
          ))}
        </p>
      )}
      {note && <p className="tool-note">{note}</p>}

      <dl className="facts">
        {call.words !== undefined && (
          <>
            <dt>words</dt>
            <dd>
              {call.words.toLocaleString('en-GB')} <ProvenanceBadge of="measured" compact />
            </dd>
          </>
        )}
        {call.score !== undefined && (
          <>
            <dt>score</dt>
            <dd>{call.score}/10</dd>
          </>
        )}
        <dt>tokens</dt>
        <dd>
          {call.tokens ? (
            <>
              {call.tokens.toLocaleString('en-GB')}{' '}
              <ProvenanceBadge
                of={call.tokens_source === 'reconstructed' ? 'reconstructed' : 'measured'}
                compact
              />
            </>
          ) : (
            <span className="muted">not recorded</span>
          )}
        </dd>
        {!cost.unpriced && (
          <>
            <dt>cost</dt>
            <dd>
              <CostTriple cost={cost} />
            </dd>
          </>
        )}
      </dl>

      {(call.note || call.reason) && <p className="callout">{call.note ?? call.reason}</p>}
    </article>
  )
}

export function Run({
  log,
  flow,
  agents,
  pricing,
}: {
  log: LogEntry[]
  flow: FlowSpec
  agents: AgentDef[]
  pricing: Pricing | null
}) {
  const calls = useMemo(() => agentCalls(log), [log])
  const tokens = useMemo(() => summariseTokens(log, pricing), [log, pricing])
  const byName = useMemo(() => new Map(agents.map((a) => [a.name, a])), [agents])

  /** Stage order comes from the spec, never from a list written here. */
  const lanes = flow.stages.map((stage) => {
    const stageCalls = calls.filter((c) => c.stage === stage.id)
    const chapters = [...new Set(stageCalls.map((c) => c.chapter).filter((n): n is number => n !== undefined))].sort(
      (a, b) => a - b,
    )
    return { stage, stageCalls, chapters }
  })

  const declaredWriters = new Set(flow.stages.filter((s) => s.writes_bible).map((s) => s.agent))
  const toolWriters = new Set(agents.filter((a) => a.tools.includes('Write')).map((a) => a.name))
  const authorityAgrees =
    declaredWriters.size === toolWriters.size && [...declaredWriters].every((n) => toolWriters.has(n))

  return (
    <div className="screen">
      <section>
        <h2>Stages</h2>
        <p className="lede">
          Six lanes, read from <code>specs/flow.yaml</code>. Inside FLOW-4, one sub-lane per chapter
          and one block per draft.
        </p>
        <p className="note">
          <strong>Duration is not recorded.</strong> Several log rows share a timestamp because it is
          written per group rather than per call, so the order is real and the spacing is not. No bar
          on this page is proportional to time.
        </p>

        <div className="lanes">
          {lanes.map(({ stage, stageCalls, chapters }) => (
            <section key={stage.id} className="lane">
              <header className="lane-head">
                <span className="lane-id">{stage.id}</span>
                <span className="lane-name">{stage.name}</span>
                <span className="lane-agent">{stage.agent}</span>
                {stage.writes_bible && (
                  <span className="badge badge-write" title="Declared writes_bible: true in specs/flow.yaml">
                    writes the Bible
                  </span>
                )}
                {stage.gate && (
                  <span className="badge" title={`min of ${stage.gate.critics?.join(', ')} ≥ ${stage.gate.threshold}`}>
                    gated
                  </span>
                )}
              </header>
              {stage.description && <p className="lane-desc">{stage.description}</p>}

              {chapters.length > 0 ? (
                chapters.map((chapter) => {
                  const iterations = [
                    ...new Set(
                      stageCalls
                        .filter((c) => c.chapter === chapter)
                        .map((c) => c.iteration ?? 1),
                    ),
                  ].sort((a, b) => a - b)
                  return (
                    <div key={chapter} className="sub-lane">
                      <h4>chapter {chapter}</h4>
                      {iterations.map((iteration) => {
                        const inDraft = stageCalls.filter(
                          (c) => c.chapter === chapter && (c.iteration ?? 1) === iteration,
                        )
                        const writer = inDraft.filter((c) => !c.agent.endsWith('-critic'))
                        const critics = inDraft.filter((c) => c.agent.endsWith('-critic'))
                        return (
                          <div key={iteration} className="draft-block">
                            <span className="draft-label">draft {iteration}</span>
                            <div className="draft-flow">
                              <div className="serial">
                                {writer.map((c, n) => (
                                  <AgentCard key={n} call={c} def={byName.get(c.agent)} pricing={pricing} />
                                ))}
                              </div>
                              {critics.length > 0 && (
                                <div className="parallel" title="These ran concurrently, dispatched in one message.">
                                  <span className="parallel-label">in parallel</span>
                                  {critics.map((c, n) => (
                                    <AgentCard key={n} call={c} def={byName.get(c.agent)} pricing={pricing} />
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )
                })
              ) : (
                <div className="serial">
                  {stageCalls.length === 0 && <p className="muted">no calls recorded for this stage</p>}
                  {stageCalls.map((c, n) => (
                    <AgentCard key={n} call={c} def={byName.get(c.agent)} pricing={pricing} />
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      </section>

      <section>
        <h2>Authority</h2>
        <p className="lede">
          The tools column is the security model. Only agents carrying <code>Write</code> can write a
          file at all; the rest return text the orchestrator writes.
        </p>
        <div className={`check check-${authorityAgrees ? 'ok' : 'bad'}`}>
          {authorityAgrees
            ? `The agents with writes_bible in flow.yaml are exactly the agents with the Write tool: ${[...toolWriters].join(', ')}.`
            : `Mismatch. flow.yaml declares ${[...declaredWriters].join(', ') || 'none'}; the Write tool is held by ${[...toolWriters].join(', ') || 'none'}.`}
        </div>
        <table className="plain">
          <thead>
            <tr>
              <th>agent</th>
              <th>model</th>
              <th>tools</th>
              <th>writes the Bible</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.name}>
                <td>{a.name}</td>
                <td>
                  <span className={`model${a.model?.includes('opus') ? ' model-heavy' : ''}`}>{a.model ?? '—'}</span>
                </td>
                <td>
                  {a.tools.length ? (
                    a.tools.map((t) => (
                      <span key={t} className={`tool tool-${t.toLowerCase()}`}>
                        {t}
                      </span>
                    ))
                  ) : (
                    <span className="muted">not declared</span>
                  )}
                </td>
                <td>{declaredWriters.has(a.name) ? 'yes' : 'no'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="note">
          Read from the front matter of <code>.claude/agents/*.md</code> — the same bytes Claude Code
          reads — and cross-checked against <code>specs/flow.yaml</code>.
        </p>
      </section>

      <section>
        <h2>Where the tokens went</h2>
        <p className="lede">
          {tokens.total.toLocaleString('en-GB')} tokens{' '}
          <ProvenanceBadge of={tokenProvenance(tokens.sources)} /> across {calls.length} calls.
        </p>
        <div className="bars">
          {tokens.byAgent.map((row) => (
            <div key={row.agent} className="bar-row">
              <span className="bar-label">{row.agent}</span>
              <span className="bar-track">
                <span
                  className={`bar-fill${row.agent.endsWith('-critic') ? ' bar-critic' : ''}`}
                  style={{ width: `${row.share * 100}%` }}
                />
              </span>
              <span className="bar-value">{row.tokens.toLocaleString('en-GB')}</span>
              <span className="bar-pct">{(row.share * 100).toFixed(1)}%</span>
            </div>
          ))}
        </div>
        <p className="finding-highlight">
          The two model critics take{' '}
          <strong>
            {(
              tokens.byAgent
                .filter((r) => r.agent.endsWith('-critic'))
                .reduce((n, r) => n + r.share, 0) * 100
            ).toFixed(0)}
            %
          </strong>{' '}
          of the run — more than the writer, the worldbuilder and the outline together. The quality
          gate is the expensive half of this system, and nothing in the manuscript would tell you
          that.
        </p>
        <p>
          Total cost: <CostTriple cost={tokens.cost} size="large" />
        </p>
        <CostNote share={pricing?.assumed_input_share} />
        {tokens.unpricedCalls > 0 && (
          <p className="note">
            {tokens.unpricedCalls} calls have no rate for their model in{' '}
            <code>config/pricing.json</code> and are counted in tokens but not in cost.
          </p>
        )}
      </section>
    </div>
  )
}
