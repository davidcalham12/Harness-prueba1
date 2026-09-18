import { useMemo, useState } from 'react'
import type { Pricing, RunIndex, RunSummary } from '../types'
import { costOf, titleFromSlug } from '../data/derive'
import { CostTriple, ProvenanceBadge } from '../components/Provenance'

const dateOf = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : null

function statusOf(run: RunSummary): { label: string; tone: 'ok' | 'warn' | 'bad' } {
  if (!run.has_state) return { label: 'incomplete', tone: 'warn' }
  if ((run.warnings ?? 0) > 0) return { label: 'accepted with warnings', tone: 'warn' }
  if (run.stage === 'complete') return { label: 'complete', tone: 'ok' }
  return { label: run.stage, tone: 'warn' }
}

function Card({
  run,
  pricing,
  current,
  writtenHere,
  onOpen,
  onRead,
  onDuplicate,
  onDiscard,
}: {
  run: RunSummary
  pricing: Pricing | null
  current: boolean
  /** Written in this browser rather than read from output/. */
  writtenHere: boolean
  onOpen: () => void
  onRead: () => void
  onDuplicate: () => void
  onDiscard: () => void
}) {
  const status = statusOf(run)
  // Priced against Opus because the writer and the Bible agents dominate a run;
  // the per-call figures on the Run screen are priced per model and are exact.
  const cost = costOf(run.tokens ?? 0, 'claude-opus-5', pricing)

  return (
    <article className={`run-card${current ? ' run-card-current' : ''}`}>
      <header>
        <h3>{titleFromSlug(run.slug)}</h3>
        <span className={`light light-${status.tone}`}>{status.label}</span>
        {writtenHere && (
          <span
            className="badge badge-write"
            title="Written in this page and kept in this browser only — not on disk, and not visible to anyone else."
          >
            written here
          </span>
        )}
        {current && <span className="badge">open</span>}
      </header>

      <p className="run-premise">
        {run.premise ?? <span className="muted">premise not recorded</span>}
      </p>

      <dl className="run-facts">
        <div>
          <dt>profile</dt>
          <dd>{run.profile ?? '—'}</dd>
        </div>
        <div>
          <dt>chapters</dt>
          <dd>{run.chapters ?? '—'}</dd>
        </div>
        <div>
          <dt>words</dt>
          <dd>{run.manuscript_words?.toLocaleString('en-GB') ?? '—'}</dd>
        </div>
        <div>
          <dt>generated</dt>
          <dd>{dateOf(run.finished_at) ?? <span className="muted">not recorded</span>}</dd>
        </div>
      </dl>

      <p className="run-retries">
        {run.retries === 0 ? (
          <>No chapter needed a rewrite.</>
        ) : (
          <>
            <strong>
              {run.retries} of {run.chapters ?? '?'} chapters
            </strong>{' '}
            needed a rewrite.
          </>
        )}
      </p>

      <p className="run-cost">
        {run.tokens ? (
          <>
            {run.tokens.toLocaleString('en-GB')} tokens{' '}
            <ProvenanceBadge
              of={
                run.tokens_source === 'reconstructed'
                  ? 'reconstructed'
                  : run.tokens_source === 'estimated'
                    ? 'estimated'
                    : 'measured'
              }
              compact
            />{' '}
            · <CostTriple cost={cost} />
          </>
        ) : (
          <span className="muted">tokens not recorded</span>
        )}
      </p>
      <p className="note note-tight">
        {writtenHere
          ? 'Estimated from the characters this page sent and received; what the page itself spent orchestrating is not counted.'
          : 'Subagent calls only — what the orchestrator itself spent is not recorded, so the real total is higher.'}
      </p>

      <footer>
        <button type="button" onClick={onOpen}>
          Open
        </button>
        <button type="button" onClick={onRead}>
          Read
        </button>
        <button type="button" onClick={onDuplicate}>
          Duplicate configuration
        </button>
        {writtenHere && (
          <button type="button" onClick={onDiscard} title="Remove it from this browser.">
            Discard
          </button>
        )}
        {run.config_hash && <code className="hash">{run.config_hash}</code>}
      </footer>
    </article>
  )
}

export function Library({
  index,
  pricing,
  currentSlug,
  writtenHere = new Set<string>(),
  unsaved = false,
  onOpen,
  onRead,
  onDuplicate,
  onNew,
  onDiscard = () => {},
}: {
  index: RunIndex | null
  pricing: Pricing | null
  currentSlug: string | null
  /** Slugs this browser wrote, as opposed to read from output/. */
  writtenHere?: Set<string>
  /** True when the browser refused to keep the last one. */
  unsaved?: boolean
  onOpen: (slug: string) => void
  onRead: (slug: string) => void
  onDuplicate: (run: RunSummary) => void
  onNew: () => void
  onDiscard?: (slug: string) => void
}) {
  const [query, setQuery] = useState('')
  const [profile, setProfile] = useState('')

  const runs = index?.runs ?? []
  const visible = useMemo(
    () =>
      runs.filter(
        (run) =>
          (!query ||
            (run.premise ?? '').toLowerCase().includes(query.toLowerCase()) ||
            run.slug.includes(query.toLowerCase())) &&
          (!profile || run.profile === profile),
      ),
    [runs, query, profile],
  )

  if (!runs.length) {
    return (
      <div className="screen">
        <section className="empty-library">
          <h2>No novels yet</h2>
          <p className="lede">
            Nothing is listed under <code>output/</code>. That is the normal state of a fresh clone:
            runs are not committed on this branch.
          </p>
          <button type="button" className="primary" onClick={onNew}>
            Write the first one
          </button>
          <p className="note">
            If you have run one already and it is not here, the index has not been rebuilt. Run{' '}
            <code>npm run index:runs</code> from <code>web/</code> and reload — a static page cannot
            list a directory, so the listing has to exist as a file.
          </p>
        </section>
      </div>
    )
  }

  return (
    <div className="screen">
      <section>
        <div className="library-head">
          <div>
            <h2>Library</h2>
            <p className="lede">
              {runs.length} novel{runs.length === 1 ? '' : 's'}, newest first.
            </p>
          </div>
          <button type="button" className="primary" onClick={onNew}>
            New novel
          </button>
        </div>

        {runs.length > 8 && (
          <div className="library-filters">
            <input
              type="search"
              id="library-search"
              placeholder="search the premise"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select id="library-profile" value={profile} onChange={(e) => setProfile(e.target.value)}>
              <option value="">every profile</option>
              {[...new Set(runs.map((r) => r.profile).filter(Boolean))].map((p) => (
                <option key={p} value={p!}>
                  {p}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="run-grid">
          {visible.map((run) => (
            <Card
              key={run.slug}
              run={run}
              pricing={pricing}
              current={run.slug === currentSlug}
              writtenHere={writtenHere.has(run.slug)}
              onOpen={() => onOpen(run.slug)}
              onRead={() => onRead(run.slug)}
              onDuplicate={() => onDuplicate(run)}
              onDiscard={() => onDiscard(run.slug)}
            />
          ))}
        </div>

        {writtenHere.size > 0 && (
          <p className="note">
            {unsaved
              ? 'A novel written here could not be kept: your browser refused to store it, so it lasts until you reload.'
              : `${writtenHere.size} of these ${writtenHere.size === 1 ? 'was' : 'were'} written in this page and kept in this browser only.`}{' '}
            They are not on disk, not visible to anyone else, and not readable by Claude. To keep one
            for good, open it and copy <code>dist/book.md</code>.
          </p>
        )}
        {index?.generated_at && (
          <p className="note">
            Index built {new Date(index.generated_at).toLocaleString('en-GB')} by{' '}
            <code>npm run index:runs</code>. A run finished since then will not appear until it is
            rebuilt.
          </p>
        )}
        <p className="note">
          No run carries a title — there is no such field in <code>state.json</code> or in the
          config. The headings above are the slug, formatted. That is a gap in the data contract, not
          a design choice.
        </p>
      </section>
    </div>
  )
}
