import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { parse as parseYaml } from 'yaml'
import fs from 'node:fs'
import path from 'node:path'

const REPO_ROOT = path.resolve(__dirname, '..')

/**
 * Paths under the repository root that the panel may read.
 *
 * This is an allowlist rather than "serve the repo", because the dev server is
 * reachable from the machine and the repository above it contains things a
 * viewer has no business fetching. Everything here is data the pipeline writes
 * or specification the pipeline reads.
 */
const ALLOWED_PREFIXES = ['output/', 'config/', 'specs/', '.claude/agents/']

const read = (p: string) => fs.readFileSync(p, 'utf8')

function allowed(rel: string): boolean {
  return ALLOWED_PREFIXES.some((p) => rel === p.slice(0, -1) || rel.startsWith(p))
}

/** Runs are directories under output/ that actually contain a run. */
function listRuns(): string[] {
  const dir = path.join(REPO_ROOT, 'output')
  if (!fs.existsSync(dir)) return []
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    .filter((slug) => {
      const base = path.join(dir, slug)
      // A run is identified by its log, not by state.json, which is only
      // written when a run finishes. An interrupted run still has a log.
      return (
        fs.existsSync(path.join(base, 'logs', 'agents.jsonl')) ||
        fs.existsSync(path.join(base, 'state.json'))
      )
    })
    .sort()
}

/** Every file the panel needs, resolved for the static build. */
function filesToCopy(): string[] {
  const out: string[] = []
  const add = (rel: string) => {
    if (fs.existsSync(path.join(REPO_ROOT, rel))) out.push(rel)
  }
  const walk = (rel: string) => {
    const abs = path.join(REPO_ROOT, rel)
    if (!fs.existsSync(abs)) return
    for (const entry of fs.readdirSync(abs, { withFileTypes: true })) {
      const child = `${rel}/${entry.name}`
      if (entry.isDirectory()) walk(child)
      else out.push(child)
    }
  }

  add('config/novel.config.json')
  add('config/pricing.json')
  walk('config/profiles')
  add('specs/flow.yaml')
  walk('.claude/agents')
  add('output/runs.json')
  for (const slug of listRuns()) walk(`output/${slug}`)
  return out
}

/**
 * Serves repository data at /data/<path>.
 *
 * This is not a backend. It computes nothing, holds no state and has no write
 * path — it is the dev server handing over files that `vite build` copies into
 * `dist/data/` verbatim, so the built panel is a directory of static files that
 * any file server (or `file://`, given a fetch-friendly browser) can host.
 */
function repoData(): Plugin {
  return {
    name: 'novaforge-repo-data',

    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url?.startsWith('/data/')) return next()

        const rel = decodeURIComponent(req.url.slice('/data/'.length).split('?')[0]!)

        if (rel === 'runs.json') {
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify(listRuns()))
          return
        }

        // Resolve FIRST, then test both containment and the allowlist against
        // the normalised path.
        //
        // Testing the allowlist against the request as sent was a real hole:
        // `output/../SECURITY.md` starts with `output/`, so it passed the
        // prefix test, and only then resolved to the repository root. The
        // allowlist has to see what will actually be opened, not what was
        // asked for. (`main`'s SEC-3 makes the same point about checking
        // containment after `realpath` rather than before.)
        const abs = path.resolve(REPO_ROOT, rel)
        const inside = abs === REPO_ROOT || abs.startsWith(REPO_ROOT + path.sep)
        const normalised = path.relative(REPO_ROOT, abs).split(path.sep).join('/')

        if (
          !inside ||
          !allowed(normalised) ||
          !fs.existsSync(abs) ||
          fs.statSync(abs).isDirectory()
        ) {
          res.statusCode = 404
          res.end('not found')
          return
        }

        const type = rel.endsWith('.json')
          ? 'application/json'
          : rel.endsWith('.jsonl')
            ? 'application/x-ndjson'
            : 'text/plain; charset=utf-8'
        res.setHeader('Content-Type', type)
        res.end(fs.readFileSync(abs))
      })
    },

    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'data/runs.json',
        source: JSON.stringify(listRuns()),
      })
      for (const rel of filesToCopy()) {
        this.emitFile({
          type: 'asset',
          fileName: `data/${rel}`,
          source: fs.readFileSync(path.join(REPO_ROOT, rel)),
        })
      }

      // JSON twins for the two files that are not a servable web media type.
      //
      // A static host will serve .jsonl and .yaml happily; a sandboxed one that
      // allowlists media types will not, and the page then loads with no log
      // and no stage list. Emitting the same content as JSON costs a few
      // kilobytes and makes the build portable to either. The loaders prefer
      // the twin and fall back, so the dev server keeps reading the originals
      // and there is exactly one source of truth on disk.
      const flow = parseYaml(read(path.join(REPO_ROOT, 'specs', 'flow.yaml')))
      this.emitFile({
        type: 'asset',
        fileName: 'data/specs/flow.json',
        source: JSON.stringify(flow),
      })

      for (const slug of listRuns()) {
        const log = path.join(REPO_ROOT, 'output', slug, 'logs', 'agents.jsonl')
        if (!fs.existsSync(log)) continue
        const rows = read(log)
          .split(/\r?\n/)
          .filter((line) => line.trim())
          .map((line) => JSON.parse(line))
        this.emitFile({
          type: 'asset',
          fileName: `data/output/${slug}/logs/agents.json`,
          source: JSON.stringify(rows),
        })
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), repoData()],
  base: './',
  server: { port: 5178, open: false },
  build: { outDir: 'dist', emptyOutDir: true },
})
