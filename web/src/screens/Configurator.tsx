import { useMemo, useState } from 'react'
import type { LogEntry, NovelConfig, Pricing } from '../types'
import {
  deepMerge,
  deltaOf,
  feasibility,
  measuredPerChapter,
  project,
  worstLight,
} from '../data/derive'
import { CostNote, CostTriple } from '../components/Provenance'

/** A leaf the form can edit, addressed by its path in the config object. */
interface Field {
  path: string[]
  label: string
  min?: number
  max?: number
  step?: number
  kind?: 'number' | 'text'
}

/**
 * The editable surface.
 *
 * Deliberately a list rather than a walk of the config object: not every leaf
 * is meaningful to change by hand, and a form that offered all of them would
 * bury the six that decide what a run costs.
 */
const FIELDS: Array<{ group: string; fields: Field[] }> = [
  {
    group: 'novel',
    fields: [
      { path: ['novel', 'chapters'], label: 'chapters', min: 1, max: 200 },
      { path: ['novel', 'tone'], label: 'tone', kind: 'text' },
      { path: ['novel', 'words_per_chapter', 'min'], label: 'words min' },
      { path: ['novel', 'words_per_chapter', 'target'], label: 'words target' },
      { path: ['novel', 'words_per_chapter', 'max'], label: 'words max' },
      { path: ['novel', 'tolerance_pct'], label: 'tolerance %', min: 0, max: 100 },
      { path: ['novel', 'lines_per_chapter', 'min'], label: 'lines min' },
      { path: ['novel', 'lines_per_chapter', 'max'], label: 'lines max' },
      { path: ['novel', 'chars_per_line', 'max'], label: 'chars per line' },
      { path: ['novel', 'paragraphs_per_chapter', 'min'], label: 'paragraphs min' },
      { path: ['novel', 'paragraphs_per_chapter', 'max'], label: 'paragraphs max' },
      { path: ['novel', 'sentences_per_paragraph', 'min'], label: 'sentences min' },
      { path: ['novel', 'sentences_per_paragraph', 'max'], label: 'sentences max' },
      { path: ['novel', 'beats_per_chapter', 'min'], label: 'beats min' },
      { path: ['novel', 'beats_per_chapter', 'max'], label: 'beats max' },
      { path: ['novel', 'promises', 'min'], label: 'promises min' },
      { path: ['novel', 'promises', 'max'], label: 'promises max' },
    ],
  },
  {
    group: 'bible',
    fields: [
      { path: ['bible', 'characters', 'min'], label: 'characters min' },
      { path: ['bible', 'characters', 'max'], label: 'characters max' },
      { path: ['bible', 'factions', 'min'], label: 'factions min' },
      { path: ['bible', 'factions', 'max'], label: 'factions max' },
      { path: ['bible', 'world_rules', 'min'], label: 'world rules min' },
      { path: ['bible', 'world_rules', 'max'], label: 'world rules max' },
      { path: ['bible', 'technology_entries', 'min'], label: 'technology min' },
      { path: ['bible', 'technology_entries', 'max'], label: 'technology max' },
      { path: ['bible', 'timeline_rows', 'min'], label: 'timeline rows min' },
      { path: ['bible', 'timeline_rows', 'max'], label: 'timeline rows max' },
      { path: ['bible', 'mysteries', 'min'], label: 'mysteries min' },
      { path: ['bible', 'mysteries', 'max'], label: 'mysteries max' },
      { path: ['bible', 'world_min_words'], label: 'world words min' },
      { path: ['bible', 'world_max_words'], label: 'world words max' },
    ],
  },
  {
    group: 'context',
    fields: [{ path: ['context', 'max_summary_words'], label: 'rolling summary cap' }],
  },
  {
    group: 'quality_gate',
    fields: [
      { path: ['quality_gate', 'threshold'], label: 'threshold', min: 0, max: 10 },
      { path: ['quality_gate', 'max_revisions'], label: 'max revisions', min: 0, max: 10 },
    ],
  },
  {
    group: 'budget',
    fields: [
      { path: ['budget', 'max_cost_usd'], label: 'max cost USD', step: 0.5 },
      { path: ['budget', 'max_calls'], label: 'max calls' },
      { path: ['budget', 'max_tokens'], label: 'max tokens' },
    ],
  },
]

function at(obj: unknown, path: string[]): unknown {
  return path.reduce<unknown>(
    (acc, key) => (acc && typeof acc === 'object' ? (acc as Record<string, unknown>)[key] : undefined),
    obj,
  )
}

function setAt(obj: Record<string, unknown>, path: string[], value: unknown): Record<string, unknown> {
  const [head, ...rest] = path
  if (head === undefined) return obj
  const out = { ...obj }
  if (rest.length === 0) {
    out[head] = value
  } else {
    const child = (out[head] ?? {}) as Record<string, unknown>
    out[head] = setAt({ ...child }, rest, value)
  }
  return out
}

export function Configurator({
  base,
  profiles,
  log,
  pricing,
  embedded = false,
}: {
  base: NovelConfig
  profiles: Record<string, NovelConfig>
  log: LogEntry[]
  pricing: Pricing | null
  /** Inside "New novel", the projection and the export live on that screen;
   *  showing them twice would be two sets of numbers to reconcile. */
  embedded?: boolean
}) {
  const [profileName, setProfileName] = useState<string>('tiny')
  const [edits, setEdits] = useState<Record<string, unknown>>({})

  const profile = profiles[profileName] ?? {}
  const withProfile = useMemo(() => deepMerge(base as Record<string, unknown>, profile), [base, profile])
  const resolved = useMemo(() => deepMerge(withProfile, edits), [withProfile, edits])

  const checks = useMemo(() => feasibility(resolved as NovelConfig), [resolved])
  const light = worstLight(checks)

  const measured = useMemo(() => measuredPerChapter(log), [log])
  const chapters = Number(at(resolved, ['novel', 'chapters']) ?? 0)
  const maxRevisions = Number(at(resolved, ['quality_gate', 'max_revisions']) ?? 0)

  const projection = useMemo(
    () =>
      project(
        chapters,
        maxRevisions,
        { writer: measured.writer, critics: measured.critics, style: measured.style },
        measured.setup,
        pricing,
      ),
    [chapters, maxRevisions, measured, pricing],
  )

  const budget = (resolved as NovelConfig).budget ?? {}
  const overCalls = budget.max_calls !== undefined && projection.maxCalls > budget.max_calls
  const overTokens = budget.max_tokens !== undefined && projection.maxTokens > budget.max_tokens
  const overCost = budget.max_cost_usd !== undefined && projection.maxCost.high > budget.max_cost_usd

  const delta = useMemo(
    () => (deltaOf(base, resolved) as Record<string, unknown> | undefined) ?? {},
    [base, resolved],
  )
  const deltaJson = JSON.stringify(delta, null, 2)

  const command = `/novaforge\n  premise: <your premise>\n  profile: ${profileName}${
    Object.keys(edits).length ? '\n  (plus the overrides in the exported JSON)' : ''
  }`

  const download = () => {
    const blob = new Blob([deltaJson], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${profileName}-custom.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="screen">
      <section>
        <h2>Compose a configuration</h2>
        <p className="lede">
          Three layers, resolved in order: the complete base, a partial profile, then your changes.
          What you export is the <strong>delta against the base</strong>, which is exactly what a
          profile file is.
        </p>

        <label className="profile-pick">
          profile
          <select value={profileName} onChange={(e) => setProfileName(e.target.value)}>
            {Object.keys(profiles).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>

        {FIELDS.map(({ group, fields }) => (
          <div key={group} className="field-group">
            <h3>{group}</h3>
            <table className="layers">
              <thead>
                <tr>
                  <th>field</th>
                  <th>base</th>
                  <th>profile</th>
                  <th>yours</th>
                  <th>effective</th>
                </tr>
              </thead>
              <tbody>
                {fields.map((field) => {
                  const key = field.path.join('.')
                  const baseValue = at(base, field.path)
                  const profileValue = at(profile, field.path)
                  const editValue = at(edits, field.path)
                  const effective = at(resolved, field.path)
                  const from =
                    editValue !== undefined ? 'yours' : profileValue !== undefined ? 'profile' : 'base'
                  return (
                    <tr key={key}>
                      <td className="field-label">{field.label}</td>
                      <td className={from === 'base' ? 'from-active' : 'muted'}>
                        {baseValue === undefined ? '—' : String(baseValue)}
                      </td>
                      <td className={from === 'profile' ? 'from-active' : 'muted'}>
                        {profileValue === undefined ? '—' : String(profileValue)}
                      </td>
                      <td>
                        <input
                          type={field.kind === 'text' ? 'text' : 'number'}
                          value={editValue === undefined ? '' : String(editValue)}
                          placeholder="—"
                          min={field.min}
                          max={field.max}
                          step={field.step}
                          onChange={(e) => {
                            const raw = e.target.value
                            setEdits((prev) => {
                              if (raw === '') {
                                // Clearing removes the override rather than
                                // writing an empty value, so the field falls
                                // back to the profile and then to the base.
                                const next = structuredClone(prev)
                                let cursor: Record<string, unknown> = next
                                for (const seg of field.path.slice(0, -1)) {
                                  cursor = (cursor[seg] ?? {}) as Record<string, unknown>
                                }
                                delete cursor[field.path[field.path.length - 1]!]
                                return next
                              }
                              return setAt(
                                prev,
                                field.path,
                                field.kind === 'text' ? raw : Number(raw),
                              )
                            })
                          }}
                        />
                      </td>
                      <td className="effective">{effective === undefined ? '—' : String(effective)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ))}
      </section>

      {!embedded && (
      <section>
        <h2>
          Feasibility <span className={`light light-${light}`}>{light}</span>
        </h2>
        <p className="lede">
          Nothing in the pipeline checks whether a configuration is physically achievable. An
          impossible one is not discovered until the length critic fails the same chapter three times
          and the gate accepts it with warnings.
        </p>
        <ul className="checks">
          {checks.map((c, n) => (
            <li key={n} className={`check check-${c.light}`}>
              <strong>{c.label}</strong> — {c.detail}
            </li>
          ))}
          {checks.length === 0 && <li className="check check-ok">nothing to check with these values</li>}
        </ul>
      </section>
      )}

      {!embedded && (
      <section>
        <h2>Projection</h2>
        <table className="plain">
          <tbody>
            <tr>
              <th>subagent calls</th>
              <td className={overCalls ? 'over' : ''}>
                {projection.minCalls.toLocaleString('en-GB')} – {projection.maxCalls.toLocaleString('en-GB')}
                {budget.max_calls !== undefined && (
                  <span className="muted"> · ceiling {budget.max_calls.toLocaleString('en-GB')}</span>
                )}
              </td>
            </tr>
            <tr>
              <th>tokens</th>
              <td className={overTokens ? 'over' : ''}>
                {Math.round(projection.minTokens).toLocaleString('en-GB')} –{' '}
                {Math.round(projection.maxTokens).toLocaleString('en-GB')}
                {budget.max_tokens !== undefined && (
                  <span className="muted"> · ceiling {budget.max_tokens.toLocaleString('en-GB')}</span>
                )}
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
                {budget.max_cost_usd !== undefined && (
                  <span className="muted"> · ceiling ${budget.max_cost_usd.toFixed(2)}</span>
                )}
              </td>
            </tr>
          </tbody>
        </table>
        <CostNote share={pricing?.assumed_input_share} />
        <p className="note">
          Extrapolated from the measured run&rsquo;s per-agent averages, not from a guess — but it is
          still an extrapolation from a three-chapter run, and a thirty-four-chapter one will not
          behave identically.
        </p>
        <p className="warn-block">
          <strong>Nothing stops a run once it starts.</strong> The <code>budget</code> block is
          advisory on this branch: no ceiling is checked before a call. This projection is the
          control, and it runs once, here, before you begin.
        </p>
      </section>
      )}

      {!embedded && (
      <section>
        <h2>Export</h2>
        <p className="lede">
          This screen exports a file and a command to copy. It launches nothing: the orchestrator is
          Claude Code in a terminal and there is no headless entry point to call.
        </p>
        <div className="export">
          <div>
            <h3>profile JSON — the delta only</h3>
            <pre className="code">{deltaJson === '{}' ? '{}  // identical to the base' : deltaJson}</pre>
            <button type="button" onClick={download}>
              download {profileName}-custom.json
            </button>
          </div>
          <div>
            <h3>command</h3>
            <pre className="code">{command}</pre>
            <button type="button" onClick={() => navigator.clipboard?.writeText(command)}>
              copy
            </button>
          </div>
        </div>
      </section>
      )}
    </div>
  )
}
