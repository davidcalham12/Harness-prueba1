import type { CostRange, Provenance } from '../types'

/**
 * The provenance badge.
 *
 * `specs/acceptance.md` marks every criterion with how it was established, and
 * the panel inherits that: no figure is rendered without one of these. The
 * distinction that matters most is `reported` — the worldbuilder said it had
 * written ~870 words when `wc -w` counted 948, so a figure an agent supplied
 * about itself is not the same kind of fact as one the orchestrator counted.
 *
 * Never colour alone: each grade carries a symbol, because a reader who cannot
 * distinguish the colours still has to be able to read the grade.
 */
const GRADES: Record<Provenance, { symbol: string; label: string; title: string }> = {
  measured: {
    symbol: '●',
    label: 'measured',
    title: 'The orchestrator counted this — wc -w, a heading scan, a file length.',
  },
  reported: {
    symbol: '◐',
    label: 'reported',
    title:
      'The agent said this about itself, and that is not reliable: the worldbuilder reported ~870 words when there were 948.',
  },
  reconstructed: {
    symbol: '◌',
    label: 'reconstructed',
    title:
      'Copied out of a session transcript after the fact, not recorded live as the run happened.',
  },
  estimated: {
    symbol: '≈',
    label: 'estimated',
    title:
      'Derived from something that was measured. A run written in this page counts the characters it sent and received — that part is exact — and converts them to tokens at roughly four characters each, which is a rule of thumb and not a measurement.',
  },
  absent: {
    symbol: '—',
    label: 'not recorded',
    title: 'The data does not carry this figure. It is a gap, not a zero.',
  },
}

export function ProvenanceBadge({
  of,
  note,
  compact,
}: {
  of: Provenance
  note?: string
  compact?: boolean
}) {
  const grade = GRADES[of]
  return (
    <span
      className={`prov prov-${of}${compact ? ' prov-compact' : ''}`}
      title={note ? `${grade.title}\n\n${note}` : grade.title}
    >
      <span aria-hidden="true">{grade.symbol}</span>
      {!compact && <span className="prov-label">{grade.label}</span>}
      <span className="sr-only">{`provenance: ${grade.label}`}</span>
    </span>
  )
}

/** A number that cannot appear without saying where it came from. */
export function Figure({
  value,
  of,
  unit,
  note,
}: {
  value: number | string | null | undefined
  of: Provenance
  unit?: string
  note?: string
}) {
  const missing = value === null || value === undefined
  return (
    <span className="figure">
      <span className="figure-value">
        {missing ? 'not recorded' : typeof value === 'number' ? value.toLocaleString('en-GB') : value}
      </span>
      {!missing && unit && <span className="figure-unit">{unit}</span>}
      <ProvenanceBadge of={missing ? 'absent' : of} note={note} compact />
    </span>
  )
}

const money = (n: number) => `$${n.toFixed(2)}`

/**
 * Cost, always as three figures.
 *
 * The harness reports one token total per call with no input/output split, so
 * the cost cannot be computed — only bounded. The two bounds are exact
 * arithmetic; the estimate between them rests on `assumed_input_share` in
 * `config/pricing.json`, which is a declared assumption. Showing the estimate
 * alone would present a judgement as a measurement.
 */
export function CostTriple({ cost, size = 'normal' }: { cost: CostRange; size?: 'normal' | 'large' }) {
  // A reported cost is not bounded, because there is nothing to bound: the
  // runner computed it. Three figures here would invent an uncertainty.
  if (cost.exact !== undefined) {
    return (
      <span className={`cost cost-${size} cost-exact`}>
        <span className="cost-estimate" title="Reported by the runner, not derived from a token count.">
          {money(cost.exact)}
        </span>
        <ProvenanceBadge of="measured" compact />
      </span>
    )
  }
  if (cost.unpriced) {
    return (
      <span className="cost cost-unpriced" title="No rate for this model in config/pricing.json. An absent cost is a gap a reader can see; a wrong one is not.">
        not priced
      </span>
    )
  }
  return (
    <span className={`cost cost-${size}`}>
      <span className="cost-bound" title="Exact: every token at the input rate.">
        {money(cost.low)}
      </span>
      <span className="cost-sep">/</span>
      <span
        className="cost-estimate"
        title={`Assumes ${Math.round(cost.assumedInputShare * 100)}% of tokens are input (assumed_input_share in config/pricing.json). This is a declared assumption, not a measurement.`}
      >
        {money(cost.estimate)}
      </span>
      <span className="cost-sep">/</span>
      <span className="cost-bound" title="Exact: every token at the output rate.">
        {money(cost.high)}
      </span>
      <span className="cost-legend">low / est / high</span>
    </span>
  )
}

/** The standing caveat, shown once per screen that reports cost. */
export function CostNote({ share, exact }: { share: number | undefined; exact?: boolean }) {
  if (exact) {
    return (
      <p className="note">
        Cost here is <strong>reported, not bounded</strong>. Claude Code computed it for each call
        and the panel added them up, so there is no assumption in it — unlike a run whose tokens
        arrive as one total with no input/output split.
      </p>
    )
  }
  return (
    <p className="note">
      Cost is <strong>bounded, not computed</strong>. The harness reports one token total per
      subagent call with no input/output split, so the two bounds are exact arithmetic and the
      middle figure assumes {share === undefined ? 'an unset share of' : `${Math.round(share * 100)}%`}{' '}
      input — a declared assumption in <code>config/pricing.json</code>, not a measurement.
    </p>
  )
}
