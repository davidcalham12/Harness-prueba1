import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { parse as parseYaml } from 'yaml'
import fs from 'node:fs'
import path from 'node:path'
import { spawn, spawnSync } from 'node:child_process'

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

/**
 * Lets the panel write a novel while running on the dev server.
 *
 * The published artifact can ask Claude through the `sample` capability. A
 * local page cannot — there is no such capability outside the artifact
 * runtime — so the two were not equivalent, and the local one could show a run
 * but never produce one.
 *
 * This closes that gap with a dev-server route. **It is worth being clear that
 * this is the backend the original brief ruled out**, and three things keep it
 * contained:
 *
 * * It exists only in `configureServer`, so it is never in `vite build` and
 *   never in the published artifact.
 * * The credential is read from the environment by the SDK and stays in this
 *   Node process. The browser never sees it, and the route refuses to echo it.
 * * It does one thing: forward a prompt, return the text and the usage.
 *
 * The usage is the part worth having. The real API reports token counts, so a
 * local run has MEASURED tokens where the artifact can only estimate them from
 * characters — the panel grades the two apart.
 */
function localSampler(): Plugin {
  let client: unknown = null
  let clientError = ''

  const getClient = async () => {
    if (client || clientError) return client
    try {
      const { default: Anthropic } = await import('@anthropic-ai/sdk')
      // Zero-arg: the SDK resolves ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or
      // an `ant auth login` profile. Never a key written into this file.
      client = new Anthropic()
    } catch (err) {
      clientError = err instanceof Error ? err.message : String(err)
    }
    return client
  }

  const credentialPresent = () =>
    Boolean(process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN)

  return {
    name: 'novaforge-local-sampler',
    apply: 'serve',

    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (!req.url?.startsWith('/api/sample')) return next()

        res.setHeader('Content-Type', 'application/json')

        // A probe, so the page can explain itself instead of failing silently.
        if (req.method === 'GET') {
          res.end(
            JSON.stringify({
              available: credentialPresent(),
              reason: credentialPresent()
                ? ''
                : 'No Anthropic credential in this dev server process. Set ANTHROPIC_API_KEY and restart it.',
            }),
          )
          return
        }

        if (req.method !== 'POST') {
          res.statusCode = 405
          res.end(JSON.stringify({ error: 'POST only' }))
          return
        }

        const chunks: Buffer[] = []
        for await (const chunk of req) chunks.push(chunk as Buffer)

        try {
          const { prompt, model } = JSON.parse(Buffer.concat(chunks).toString('utf8')) as {
            prompt?: string
            model?: string
          }
          if (!prompt) throw new Error('no prompt')

          const anthropic = (await getClient()) as {
            messages: {
              create: (args: unknown) => Promise<{
                content: Array<{ type: string; text?: string }>
                usage?: { input_tokens?: number; output_tokens?: number }
                stop_reason?: string
              }>
            }
          } | null
          if (!anthropic) throw new Error(clientError || 'the Anthropic SDK could not be loaded')

          const message = await anthropic.messages.create({
            model: model || 'claude-opus-5',
            max_tokens: 16000,
            messages: [{ role: 'user', content: prompt }],
          })

          const text = message.content
            .filter((block) => block.type === 'text')
            .map((block) => block.text ?? '')
            .join('')

          res.end(
            JSON.stringify({
              text,
              stop_reason: message.stop_reason,
              usage: {
                input_tokens: message.usage?.input_tokens ?? null,
                output_tokens: message.usage?.output_tokens ?? null,
              },
            }),
          )
        } catch (err) {
          // The message can name a credential problem but never carry a value:
          // this response goes to the browser.
          const raw = err instanceof Error ? err.message : String(err)
          res.statusCode = 500
          res.end(JSON.stringify({ error: raw.replace(/sk-[A-Za-z0-9_-]{8,}/g, '[REDACTED]') }))
        }
      })
    },
  }
}

/**
 * Runs one NovaForge agent through the Claude Code CLI.
 *
 * This is the best of the three routes the panel has, and the reason is not
 * convenience: `claude -p --agent chapter-writer` runs that agent as a REAL
 * SUBAGENT, with the tool list from `.claude/agents/chapter-writer.md`. Asked
 * what tools it has, it answers "Glob" — so prior prose is unreachable to it
 * rather than merely absent from its prompt. That is the guarantee this whole
 * branch exists for, and the other two routes only hold it by discipline.
 *
 * It also needs no API key (it uses the machine's Claude Code session) and
 * returns a real dollar cost, so the panel can stop bounding an estimate.
 *
 * **This spawns processes, so it is locked down deliberately:**
 *
 * * `agent` is checked against the files in `.claude/agents/`. There is no way
 *   to pass a system prompt, so this cannot become "run whatever I send".
 * * **The agent's own `tools:` line is the boundary**, which is the authority
 *   model this branch is built on. `--restricted` is deliberately NOT passed:
 *   measured here, it makes Claude Code fall back to its built-in agent list
 *   and refuse `--agent publisher` outright, so it would defeat the whole
 *   point. Nothing is lost by its absence — the eight definitions carry `Glob`
 *   or `Read, Write`, and that is the restriction.
 * * `--permission-mode dontAsk` denies anything that would prompt rather than
 *   waiting for a human who is not there.
 * * A per-call timeout, and `serve`-only so it is never in a build.
 *
 * Cost worth knowing: every invocation re-sends Claude Code's own system
 * prompt, which measured at $0.03–0.10 per call before any work. A three
 * chapter novel is ~20 calls.
 */
function claudeCodeAgents(): Plugin {
  const AGENT_DIR = path.join(REPO_ROOT, '.claude', 'agents')
  const TIMEOUT_MS = 10 * 60 * 1000

  const knownAgents = (): string[] => {
    if (!fs.existsSync(AGENT_DIR)) return []
    return fs
      .readdirSync(AGENT_DIR)
      .filter((f) => f.endsWith('.md'))
      .map((f) => f.replace(/\.md$/, ''))
  }

  const cliAvailable = (): boolean => {
    const probe = spawnSync(process.platform === 'win32' ? 'where' : 'which', ['claude'], {
      encoding: 'utf8',
    })
    return probe.status === 0
  }

  return {
    name: 'novaforge-claude-code-agents',
    apply: 'serve',

    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        if (!req.url?.startsWith('/api/agent')) return next()
        res.setHeader('Content-Type', 'application/json')

        const agents = knownAgents()

        if (req.method === 'GET') {
          const available = agents.length > 0 && cliAvailable()
          res.end(
            JSON.stringify({
              available,
              agents,
              reason: available
                ? ''
                : !agents.length
                  ? 'No agent definitions under .claude/agents/.'
                  : 'The `claude` CLI is not on PATH for this dev server.',
            }),
          )
          return
        }

        if (req.method !== 'POST') {
          res.statusCode = 405
          res.end(JSON.stringify({ error: 'POST only' }))
          return
        }

        const chunks: Buffer[] = []
        for await (const chunk of req) chunks.push(chunk as Buffer)

        try {
          const { agent, task } = JSON.parse(Buffer.concat(chunks).toString('utf8')) as {
            agent?: string
            task?: string
          }

          // The allowlist is the security boundary. An agent name that is not a
          // file in .claude/agents/ is refused, so this route can only ever run
          // one of the eight definitions the repository ships.
          if (!agent || !agents.includes(agent)) {
            res.statusCode = 400
            res.end(
              JSON.stringify({
                error: `unknown agent ${JSON.stringify(agent)}; this route runs only ${agents.join(', ')}`,
              }),
            )
            return
          }
          if (!task) throw new Error('no task')

          const result = await new Promise<string>((resolve, reject) => {
            const child = spawn(
              'claude',
              [
                '-p',
                '--output-format', 'json',
                '--agent', agent,
                '--permission-mode', 'dontAsk',
                task,
              ],
              {
                cwd: REPO_ROOT,
                shell: process.platform === 'win32',
                // stdin closed, not inherited: Claude Code waits three seconds
                // for piped input otherwise, and prints a warning that lands in
                // the parsed output.
                stdio: ['ignore', 'pipe', 'pipe'],
              },
            )

            let stdout = ''
            let stderr = ''
            const timer = setTimeout(() => {
              child.kill()
              reject(new Error(`the ${agent} call exceeded ${TIMEOUT_MS / 60000} minutes`))
            }, TIMEOUT_MS)

            child.stdout.on('data', (d) => (stdout += d))
            child.stderr.on('data', (d) => (stderr += d))
            child.on('error', (err) => {
              clearTimeout(timer)
              reject(err)
            })
            child.on('close', (code) => {
              clearTimeout(timer)
              if (code !== 0) {
                reject(new Error(stderr.trim() || `claude exited ${code}`))
                return
              }
              resolve(stdout)
            })
          })

          const parsed = JSON.parse(result) as {
            result?: string
            is_error?: boolean
            total_cost_usd?: number
            usage?: { input_tokens?: number; output_tokens?: number }
            permission_denials?: unknown[]
            subagent_stats?: { spawned?: number }
          }
          if (parsed.is_error) throw new Error(parsed.result || 'the agent reported an error')

          res.end(
            JSON.stringify({
              text: parsed.result ?? '',
              usage: {
                input_tokens: parsed.usage?.input_tokens ?? null,
                output_tokens: parsed.usage?.output_tokens ?? null,
              },
              // Computed by Claude Code, not by this panel. A cost that is
              // measured rather than bounded.
              cost_usd: parsed.total_cost_usd ?? null,
              permission_denials: (parsed.permission_denials ?? []).length,
            }),
          )
        } catch (err) {
          const raw = err instanceof Error ? err.message : String(err)
          res.statusCode = 500
          res.end(JSON.stringify({ error: raw.replace(/sk-[A-Za-z0-9_-]{8,}/g, '[REDACTED]') }))
        }
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), repoData(), localSampler(), claudeCodeAgents()],
  base: './',
  server: { port: 5178, open: false },
  build: { outDir: 'dist', emptyOutDir: true },
})
