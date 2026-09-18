import { useEffect, useMemo, useState } from 'react'
import type { RunState } from '../types'
import { loadDoc } from '../data/load'
import { renderMarkdown, structureLeaks } from '../data/markdown'

interface DocEntry {
  rel: string
  label: string
  group: string
}

/** What a finished run writes, in reading order. */
function documents(state: RunState | null, chapters: number): DocEntry[] {
  const n = state?.chapters.length ?? chapters
  const docs: DocEntry[] = [
    { rel: 'bible/world.md', label: 'world', group: 'Story Bible' },
    { rel: 'bible/characters.md', label: 'characters', group: 'Story Bible' },
    { rel: 'bible/timeline.md', label: 'timeline', group: 'Story Bible' },
    { rel: 'bible/mysteries.md', label: 'mysteries', group: 'Story Bible' },
    { rel: 'outline.md', label: 'outline', group: 'Plan' },
  ]
  for (let i = 1; i <= n; i += 1) {
    const id = String(i).padStart(2, '0')
    docs.push({ rel: `chapters/ch${id}.final.md`, label: `chapter ${i}`, group: 'Chapters' })
  }
  for (let i = 1; i <= n; i += 1) {
    const id = String(i).padStart(2, '0')
    docs.push({ rel: `chapters/ch${id}.summary.md`, label: `summary ${i}`, group: 'Summaries' })
  }
  docs.push({ rel: 'chapters/rolling.summary.md', label: 'rolling summary', group: 'Summaries' })
  docs.push({ rel: 'synopsis.md', label: 'synopsis', group: 'Published' })
  docs.push({ rel: 'dist/book.md', label: 'book.md', group: 'Published' })
  return docs
}

export function Manuscript({
  slug,
  state,
  docs,
}: {
  slug: string
  state: RunState | null
  /** Present for a run written in this page: its documents never touched disk. */
  docs?: Record<string, string>
}) {
  const entries = useMemo(() => documents(state, 3), [state])
  const [selected, setSelected] = useState<string>(entries[0]?.rel ?? '')
  const [source, setSource] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // A cross-reference from a finding lands here via the hash.
  useEffect(() => {
    const jump = () => {
      const hash = decodeURIComponent(window.location.hash)
      if (hash.startsWith('#doc:')) {
        const target = hash.slice('#doc:'.length)
        const match = entries.find((d) => d.rel === target || d.rel.endsWith(target))
        if (match) setSelected(match.rel)
      }
    }
    jump()
    window.addEventListener('hashchange', jump)
    return () => window.removeEventListener('hashchange', jump)
  }, [entries])

  useEffect(() => {
    if (docs) {
      setSource(docs[selected] ?? null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    loadDoc(slug, selected).then((text) => {
      if (!cancelled) {
        setSource(text)
        setLoading(false)
      }
    })
    return () => {
      cancelled = true
    }
  }, [slug, selected, docs])

  const rendered = useMemo(() => (source ? renderMarkdown(source) : null), [source])
  const leaks = useMemo(
    () => (source && selected.startsWith('chapters/') ? structureLeaks(source) : []),
    [source, selected],
  )

  const groups = [...new Set(entries.map((d) => d.group))]

  return (
    <div className="screen manuscript">
      <nav className="doc-nav">
        {groups.map((group) => (
          <div key={group}>
            <h3>{group}</h3>
            <ul>
              {entries
                .filter((d) => d.group === group)
                .map((d) => (
                  <li key={d.rel}>
                    <button
                      type="button"
                      className={d.rel === selected ? 'active' : ''}
                      onClick={() => setSelected(d.rel)}
                    >
                      {d.label}
                    </button>
                  </li>
                ))}
            </ul>
          </div>
        ))}
      </nav>

      <article className="doc">
        <header className="doc-head">
          <code>{selected}</code>
          {source && (
            <span className="muted">
              {source.split(/\s+/).filter(Boolean).length.toLocaleString('en-GB')} words
            </span>
          )}
        </header>

        {leaks.length > 0 && (
          <div className="check check-bad">
            <strong>{leaks.length} prose line(s) begin with Markdown structure.</strong> This branch
            does not escape output before concatenating chapters into <code>dist/book.md</code>, so a
            paragraph opening with <code>## </code> becomes a chapter heading in the assembled book.
            On <code>main</code> this was escaped (SEC-5).
            <ul>
              {leaks.map((l) => (
                <li key={l.line}>
                  line {l.line}: <code>{l.text}</code>
                </li>
              ))}
            </ul>
          </div>
        )}
        {leaks.length === 0 && selected.startsWith('chapters/') && source && (
          <div className="check check-ok">
            No prose line begins with Markdown structure. Nothing prevents it — the check is here
            because the pipeline has no escaping.
          </div>
        )}

        {loading && <p className="muted">loading…</p>}
        {!loading && source === null && (
          <p className="muted">
            Not present in this run. That is a normal state for a run that stopped early, or for an
            artefact this branch does not produce.
          </p>
        )}
        {rendered && (
          <div className="prose" dangerouslySetInnerHTML={{ __html: rendered.html }} />
        )}
      </article>
    </div>
  )
}
