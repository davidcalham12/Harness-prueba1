/**
 * Renders every screen once, against the committed run, and fails loudly.
 *
 * `npm test` proves the derivations are right and `tsc` proves the types line
 * up; neither runs a component. This does — a crash in a render path, a `.map`
 * on something that is undefined in the real data, a key that only exists in
 * the type, all surface here rather than as a blank page.
 *
 * Built with `vite build --ssr` so the JSX and the TypeScript go through the
 * same transform the browser bundle does, then executed under Node.
 *
 * `Manuscript` and `App` are not rendered here: both reach for `window` or
 * `fetch` during mount, which is a browser concern rather than a render one.
 * Their absence is the known limit of this check.
 */
import { renderToString } from 'react-dom/server'
import fs from 'node:fs'
import path from 'node:path'

import { classify } from './src/data/load'
import { gateTable } from './src/data/derive'
import { Quality } from './src/screens/Quality'
import { Run } from './src/screens/Run'
import { Configurator } from './src/screens/Configurator'
import { Presentation } from './src/screens/Presentation'
import { ContextChart } from './src/components/ContextChart'
import { Library } from './src/screens/Library'
import { NewNovel } from './src/screens/NewNovel'
import { Diagram } from './src/screens/Diagram'
import { WhyRepeated } from './src/components/WhyRepeated'
import { parseFrontMatter } from './src/data/load'
import { parse as parseYaml } from 'yaml'
import type { AgentDef, Critique, FlowSpec, LogEntry, NovelConfig, Pricing, RunIndex } from './src/types'

// Resolved from the working directory, not from the module: the SSR bundle
// lands in dist-ssr/ and `import.meta.dirname` would point there. This script
// is meant to be run as `npm run render-check` from web/.
const ROOT = path.resolve(process.cwd(), '..')
const RUN = path.join(ROOT, 'output', 'deep-space-salvage-derelict')
const read = (p: string) => fs.readFileSync(p, 'utf8')
const readJson = <T,>(p: string): T => JSON.parse(read(p)) as T

const log: LogEntry[] = read(path.join(RUN, 'logs', 'agents.jsonl'))
  .trim()
  .split('\n')
  .map((line) => classify(JSON.parse(line)))

const state = readJson<Parameters<typeof Quality>[0]['state']>(path.join(RUN, 'state.json'))
const pricing = readJson<Pricing>(path.join(ROOT, 'config', 'pricing.json'))
const base = readJson<NovelConfig>(path.join(ROOT, 'config', 'novel.config.json'))
const flow = parseYaml(read(path.join(ROOT, 'specs', 'flow.yaml'))) as FlowSpec

const profiles: Record<string, NovelConfig> = {}
for (const name of ['tiny', 'small', 'medium', 'full']) {
  const file = path.join(ROOT, 'config', 'profiles', `${name}.json`)
  if (fs.existsSync(file)) profiles[name] = readJson<NovelConfig>(file)
}

const agents: AgentDef[] = fs
  .readdirSync(path.join(ROOT, '.claude', 'agents'))
  .filter((f) => f.endsWith('.md'))
  .map((f) => {
    const { meta, body } = parseFrontMatter(read(path.join(ROOT, '.claude', 'agents', f)))
    return {
      name: meta.name ?? f.replace(/\.md$/, ''),
      description: meta.description,
      tools: meta.tools ? meta.tools.split(',').map((t) => t.trim()).filter(Boolean) : [],
      model: meta.model,
      body,
    }
  })

const runIndex = readJson<RunIndex>(path.join(ROOT, 'output', 'runs.json'))

const { critics, rows } = gateTable(log)
const critiques: Critique[] = []
for (const chapter of [...new Set(rows.map((r) => r.chapter))]) {
  for (const critic of critics) {
    const file = path.join(RUN, 'critiques', `ch${String(chapter).padStart(2, '0')}.${critic}.json`)
    if (fs.existsSync(file)) critiques.push(readJson<Critique>(file))
  }
}

interface Case {
  name: string
  render: () => string
  /** Strings that must appear, so a screen cannot pass by rendering nothing. */
  expect: string[]
}

const cases: Case[] = [
  {
    name: 'Quality',
    render: () => renderToString(<Quality log={log} critiques={critiques} state={state} />),
    expect: [
      'retry',
      'continuity',
      'overruled',
      'the critics disagreed',
      'not passed to the writer',
      'Incidents',
      'Draft evolution',
    ],
  },
  {
    name: 'Run',
    render: () => renderToString(<Run log={log} flow={flow} agents={agents} pricing={pricing} />),
    expect: ['FLOW-1', 'FLOW-6', 'chapter-writer', 'Glob', 'in parallel', 'writes the Bible'],
  },
  {
    name: 'Configurator',
    render: () =>
      renderToString(<Configurator base={base} profiles={profiles} log={log} pricing={pricing} />),
    expect: ['Feasibility', 'Projection', 'subagent calls', 'low / est / high'],
  },
  {
    name: 'Presentation',
    render: () => renderToString(<Presentation log={log} />),
    expect: ['Replay', 'play'],
  },
  {
    name: 'ContextChart',
    render: () => renderToString(<ContextChart log={log} />),
    expect: ['flat', 'proxy'],
  },
  {
    // A run with no usage at all -- which is what an in-page run looked like
    // before it counted characters, and what any run with a partial log looks
    // like. It must say "not recorded", not draw a line through zeros and
    // announce a 100% spread.
    name: 'ContextChart (no usage)',
    render: () =>
      renderToString(
        <ContextChart
          log={log.map((e) =>
            e.kind === 'agent_call' ? { ...e, tokens: undefined, prompt_chars: undefined } : e,
          )}
        />,
      ),
    expect: ['Not recorded', 'nothing to plot'],
  },
  {
    name: 'Run (no usage)',
    render: () =>
      renderToString(
        <Run
          log={log.map((e) => (e.kind === 'agent_call' ? { ...e, tokens: undefined } : e))}
          flow={flow}
          agents={agents}
          pricing={pricing}
          critiques={critiques}
        />,
      ),
    expect: ['Not recorded for this run', 'gap, not a zero'],
  },
  {
    name: 'Library',
    render: () =>
      renderToString(
        <Library
          index={runIndex}
          pricing={pricing}
          currentSlug={null}
          onOpen={() => {}}
          onRead={() => {}}
          onDuplicate={() => {}}
          onNew={() => {}}
        />,
      ),
    // The title is the formatted slug, which is the documented stand-in for a
    // field the data contract does not have.
    expect: ['Deep Space Salvage Derelict', 'needed a rewrite', 'Duplicate configuration'],
  },
  {
    name: 'Library (empty)',
    render: () =>
      renderToString(
        <Library
          index={{ generated_at: '', runs: [] }}
          pricing={pricing}
          currentSlug={null}
          onOpen={() => {}}
          onRead={() => {}}
          onDuplicate={() => {}}
          onNew={() => {}}
        />,
      ),
    expect: ['No novels yet', 'index:runs'],
  },
  {
    name: 'NewNovel',
    render: () =>
      renderToString(
        <NewNovel
          base={base}
          profiles={profiles}
          log={log}
          pricing={pricing}
          seed={null}
          onSeedConsumed={() => {}}
          agents={agents}
          flow={flow}
          onGenerated={() => {}}
        />,
      ),
    expect: [
      'What should it be about',
      'How many chapters',
      'lines per chapter',
      'runs in your terminal',
      'Nothing stops a run once it starts',
      // Without the sample capability — which is the case under SSR — the page
      // must still offer the terminal route and nothing else.
      'Get the command instead',
    ],
  },
  {
    name: 'Diagram',
    render: () =>
      renderToString(
        <Diagram flow={flow} log={log} critiques={critiques} onJump={() => {}} />,
      ),
    expect: ['FLOW-1', 'orchestrator', 'generated from', 'out of date'],
  },
  {
    name: 'WhyRepeated',
    render: () => renderToString(<WhyRepeated log={log} critiques={critiques} />),
    // Asserted on strings that do not span a JSX interpolation: React's SSR
    // puts comment markers between text nodes, so "Chapter {n}, draft {i}"
    // never appears as one run of characters in the HTML even though it does
    // on screen.
    expect: [
      'written twice',
      'rewritten',
      'reached the writer',   // the overruled finding in chapter 3
      'What changed',
      'what was checked',
      'timeline arithmetic',  // a finding kind, translated
      'overruled by the orchestrator',
    ],
  },
]

let failures = 0
for (const item of cases) {
  try {
    const html = item.render()
    const missing = item.expect.filter((needle) => !html.includes(needle))
    if (missing.length) {
      failures += 1
      console.log(`FAIL  ${item.name} rendered ${html.length} chars but is missing: ${missing.join(', ')}`)
    } else {
      console.log(`PASS  ${item.name} (${html.length.toLocaleString('en-GB')} chars)`)
    }
  } catch (err) {
    failures += 1
    console.log(`FAIL  ${item.name} threw: ${err instanceof Error ? err.stack : String(err)}`)
  }
}

console.log(failures ? `\n${failures} screen(s) failed to render` : '\nevery screen renders')
process.exit(failures ? 1 : 0)
