/**
 * A small Markdown renderer for the documents a run produces.
 *
 * Hand-written rather than pulled in, for two reasons. The project's own house
 * style is to avoid dependencies it can do without; and more importantly, this
 * text was written by a model, so **every character is escaped before any
 * markup is applied**. A library that passes raw HTML through by default —
 * which most do — would turn model output into a script injection in a viewer
 * whose whole job is to display model output.
 *
 * It covers what the pipeline actually emits: headings, paragraphs, bullet
 * lists, two-column tables, blockquotes, horizontal rules, bold, italic and
 * inline code. Anything else renders as plain text, which is the right failure.
 */

export interface MarkdownBlock {
  /** A stable id so a cross-reference can scroll to a heading. */
  id?: string
  html: string
}

const escapeHtml = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

/** Inline spans, applied to already-escaped text. */
function inline(escaped: string): string {
  return escaped
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/(^|[\s(])_([^_\n]+)_/g, '$1<em>$2</em>')
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
}

function renderTable(rows: string[]): string {
  const cells = (line: string) =>
    line
      .replace(/^\||\|$/g, '')
      .split('|')
      .map((c) => inline(escapeHtml(c.trim())))

  const [header, , ...body] = rows
  const head = header ? `<tr>${cells(header).map((c) => `<th>${c}</th>`).join('')}</tr>` : ''
  const rest = body
    .map((r) => `<tr>${cells(r).map((c) => `<td>${c}</td>`).join('')}</tr>`)
    .join('')
  return `<table><thead>${head}</thead><tbody>${rest}</tbody></table>`
}

export interface RenderedMarkdown {
  html: string
  headings: Array<{ level: number; text: string; id: string }>
}

export function renderMarkdown(source: string): RenderedMarkdown {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  const headings: RenderedMarkdown['headings'] = []

  let i = 0
  while (i < lines.length) {
    const line = lines[i]!

    if (!line.trim()) {
      i += 1
      continue
    }

    // Horizontal rule
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      out.push('<hr />')
      i += 1
      continue
    }

    // Heading
    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1]!.length
      const raw = heading[2]!.trim()
      const id = slugify(raw)
      headings.push({ level, text: raw, id })
      out.push(`<h${level} id="${id}">${inline(escapeHtml(raw))}</h${level}>`)
      i += 1
      continue
    }

    // Table: a pipe row followed by a separator row
    if (line.trim().startsWith('|') && lines[i + 1]?.trim().startsWith('|')) {
      const block: string[] = []
      while (i < lines.length && lines[i]!.trim().startsWith('|')) {
        block.push(lines[i]!)
        i += 1
      }
      out.push(renderTable(block))
      continue
    }

    // Blockquote
    if (line.trim().startsWith('>')) {
      const block: string[] = []
      while (i < lines.length && lines[i]!.trim().startsWith('>')) {
        block.push(lines[i]!.replace(/^\s*>\s?/, ''))
        i += 1
      }
      out.push(`<blockquote>${inline(escapeHtml(block.join(' ')))}</blockquote>`)
      continue
    }

    // Bullet list, one level
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i]!)) {
        items.push(lines[i]!.replace(/^\s*[-*]\s+/, ''))
        i += 1
      }
      out.push(`<ul>${items.map((t) => `<li>${inline(escapeHtml(t))}</li>`).join('')}</ul>`)
      continue
    }

    // Ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i]!)) {
        items.push(lines[i]!.replace(/^\s*\d+\.\s+/, ''))
        i += 1
      }
      out.push(`<ol>${items.map((t) => `<li>${inline(escapeHtml(t))}</li>`).join('')}</ol>`)
      continue
    }

    // Paragraph: consume until a blank line or a line that starts a block
    const para: string[] = []
    while (
      i < lines.length &&
      lines[i]!.trim() &&
      !/^(#{1,6}\s|\s*[-*]\s|\s*\d+\.\s|\s*>|\|)/.test(lines[i]!) &&
      !/^\s*(-{3,}|\*{3,})\s*$/.test(lines[i]!)
    ) {
      para.push(lines[i]!)
      i += 1
    }
    out.push(`<p>${inline(escapeHtml(para.join(' ')))}</p>`)
  }

  return { html: out.join('\n'), headings }
}

/**
 * Paragraphs of prose that begin with Markdown structure.
 *
 * The pipeline does not escape its output before concatenating chapters into
 * `dist/book.md`, so a paragraph that happens to open with `## ` becomes a
 * chapter heading in the assembled book and the structure is wrong in a way
 * nobody notices until it is read. `main` escaped this (SEC-5); this branch
 * does not. It did not happen in the saved run, and nothing prevents it.
 *
 * The chapter's own opening `# Chapter N` heading is expected and not reported.
 */
export function structureLeaks(source: string): Array<{ line: number; text: string }> {
  const found: Array<{ line: number; text: string }> = []
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  lines.forEach((line, index) => {
    if (index === 0 && /^#\s+Chapter\b/.test(line)) return
    if (/^(#{1,6}\s|>\s|\s*[-*]\s|\s*\d+\.\s)/.test(line)) {
      found.push({ line: index + 1, text: line.slice(0, 120) })
    }
  })
  return found
}
