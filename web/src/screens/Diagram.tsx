import { useMemo } from 'react'
import type { FlowSpec, LogEntry } from '../types'
import { agentCalls, gateTable, orchestratorActivity } from '../data/derive'
import type { Critique } from '../types'

/**
 * The pipeline, drawn from the spec rather than from a copy of it.
 *
 * `docs/novaforge_flow.mermaid` exists and is good, but its own header sets the
 * rule it is now breaking: *"the executable version is specs/flow.yaml … if the
 * two disagree, the YAML is what actually happens and this file is the bug."*
 * It was written for `main` and five of its claims are no longer true on this
 * branch — it shows a hash-chained log, a `flow_id` field, three critics, a
 * "Science Auditor" that is called `science-critic` here, and a PDF that is not
 * produced. A sixth thing it never had is the orchestrator, which leaves the
 * gate as a diamond belonging to nobody.
 *
 * So this screen generates the picture from `specs/flow.yaml` instead of
 * maintaining a second copy. Reorder a stage or change a threshold and the
 * drawing follows, which is precisely the failure mode the original has.
 * The original file is left alone: it documents the Python architecture and is
 * not this screen's to edit.
 */

interface StageState {
  reached: boolean
  retries: number
  chapters: number
}

export function Diagram({
  flow,
  log,
  critiques,
  onJump,
}: {
  flow: FlowSpec
  log: LogEntry[]
  critiques: Critique[]
  onJump: (target: 'quality' | 'run' | 'manuscript') => void
}) {
  const calls = useMemo(() => agentCalls(log), [log])
  const { rows } = useMemo(() => gateTable(log), [log])
  const activity = useMemo(() => orchestratorActivity(log, critiques), [log, critiques])

  const stateOf = (stageId: string): StageState => {
    const mine = calls.filter((c) => c.stage === stageId)
    const chapters = new Set(mine.map((c) => c.chapter).filter((n) => n !== undefined)).size
    return {
      reached: mine.length > 0 || log.some((e) => e.kind === 'stage_complete' && e.stage === stageId),
      retries: rows.filter((r) => r.verdict === 'retry').length,
      chapters,
    }
  }

  return (
    <div className="screen">
      <section>
        <h2>The pipeline</h2>
        <p className="lede">
          Six stages, read from <code>specs/flow.yaml</code> and coloured with what this run actually
          did. Click a stage to go to its detail.
        </p>

        <div className="pipeline">
          {/* The orchestrator is a lane that spans every stage, not a box among
              the boxes: the agents appear and finish, it is there throughout. */}
          <div className="orchestrator-rail">
            <span className="rail-label">orchestrator · Claude Code</span>
            <span className="rail-detail">
              dispatches every agent · runs {activity.criticsRunLocally.join(' and ') || 'the arithmetic critics'} itself ·{' '}
              {activity.gateDecisions} gate decisions
              {activity.disagreementsArbitrated > 0 &&
                ` · ${activity.disagreementsArbitrated} arbitration${activity.disagreementsArbitrated === 1 ? '' : 's'}`}
              {activity.preGateRejections > 0 &&
                ` · ${activity.preGateRejections} rejection${activity.preGateRejections === 1 ? '' : 's'} before the gate`}
            </span>
          </div>

          <div className="stage-flow">
            {flow.stages.map((stage, index) => {
              const state = stateOf(stage.id)
              const gated = Boolean(stage.gate)
              return (
                <div key={stage.id} className="stage-wrap">
                  <button
                    type="button"
                    className={`stage-node${state.reached ? ' stage-done' : ''}${gated ? ' stage-gated' : ''}`}
                    onClick={() => onJump(gated ? 'quality' : 'run')}
                  >
                    <span className="stage-id">{stage.id}</span>
                    <span className="stage-name">{stage.name}</span>
                    <span className="stage-agent">{stage.agent}</span>
                    {stage.writes_bible && <span className="badge badge-write">writes the Bible</span>}
                    {stage.outputs && (
                      <span className="stage-outputs">
                        {stage.outputs.slice(0, 3).join(' · ')}
                      </span>
                    )}
                  </button>

                  {gated && stage.gate && (
                    <div className="gate-node">
                      <span className="gate-title">
                        gate · min of {stage.gate.critics?.length ?? 0} ≥ {stage.gate.threshold}
                      </span>
                      <div className="gate-critics">
                        {(stage.gate.critics ?? []).map((critic) => {
                          const arithmetic =
                            critiques.find((c) => c.critic === critic)?.kind === 'arithmetic' ||
                            critic === 'length' ||
                            critic === 'chatter'
                          return (
                            <span
                              key={critic}
                              className={`gate-critic ${arithmetic ? 'critic-local' : 'critic-sub'}`}
                              title={
                                arithmetic
                                  ? 'Run by the orchestrator in the shell. Reproduces.'
                                  : 'A subagent with a model. Does not reproduce.'
                              }
                            >
                              {critic}
                              <em>{arithmetic ? 'orchestrator' : 'subagent'}</em>
                            </span>
                          )
                        })}
                      </div>
                      <div className="gate-exits">
                        <span className="exit exit-pass">≥ threshold → accept</span>
                        <span className="exit exit-retry">
                          &lt; threshold, drafts left → retry
                          {state.retries > 0 && <strong> ({state.retries} this run)</strong>}
                        </span>
                        <span className="exit exit-warn">drafts spent → {stage.on_fail}</span>
                      </div>
                    </div>
                  )}

                  {index < flow.stages.length - 1 && <span className="stage-arrow" aria-hidden="true">↓</span>}
                </div>
              )
            })}
          </div>

          <button type="button" className="artefact-node" onClick={() => onJump('manuscript')}>
            dist/book.md — assembled by the orchestrator in the shell, not by an agent
          </button>
        </div>

        <div className="check check-warn">
          <strong>This drawing is generated from <code>specs/flow.yaml</code>.</strong> The
          repository also ships <code>docs/novaforge_flow.mermaid</code>, which documents the Python
          implementation on <code>main</code> and is out of date here: it shows a hash-chained log
          (this branch's is a flat file), a <code>flow_id</code> field (the rows carry{' '}
          <code>config_hash</code>), three critics rather than four, a "Science Auditor" that is
          named <code>science-critic</code>, a PDF that is not produced, and no orchestrator at all.
          That file is left untouched — generating from the spec is what stops this one going the
          same way.
        </div>
      </section>
    </div>
  )
}
