import fs from 'node:fs'
import path from 'node:path'
import { classify } from './src/data/load.ts'
import { gateTable, summariseTokens, discrepancies, agentCalls, disagreements, feasibility, deltaOf, deepMerge, tokenProvenance, orchestratorActivity, actorOf, runLocally, deriveFromLines, titleFromSlug, slugifyPremise } from './src/data/derive.ts'

const W = 'C:/Users/student/Desktop/novaforge/output/deep-space-salvage-derelict'
const R = 'C:/Users/student/Desktop/novaforge'
const log = fs.readFileSync(`${W}/logs/agents.jsonl`,'utf8').trim().split('\n').map(l=>classify(JSON.parse(l)))
const state = JSON.parse(fs.readFileSync(`${W}/state.json`,'utf8'))
const pricing = JSON.parse(fs.readFileSync(`${R}/config/pricing.json`,'utf8'))
const base = JSON.parse(fs.readFileSync(`${R}/config/novel.config.json`,'utf8'))
const tiny = JSON.parse(fs.readFileSync(`${R}/config/profiles/tiny.json`,'utf8'))

let fails = 0
const check = (name: string, cond: boolean, got?: unknown) => {
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${name}${cond ? '' : `  -> ${JSON.stringify(got)}`}`)
  if (!cond) fails++
}

const { critics, rows } = gateTable(log)
check('4 critic columns derived from data', critics.length === 4, critics)
check('5 gate rows', rows.length === 5, rows.length)
check('ch02 d1 retries, worst is continuity',
  rows[1].verdict === 'retry' && rows[1].worst.join() === 'continuity', rows[1])
check('ch03 d1 retries, worst is continuity',
  rows[3].verdict === 'retry' && rows[3].worst.join() === 'continuity', rows[3])
check('ch01 accepted first draft', rows[0].verdict === 'accept' && rows[0].aggregate === 10)

const t = summariseTokens(log, pricing)
check('281,202 tokens', t.total === 281202, t.total)
check('provenance is reconstructed', tokenProvenance(t.sources) === 'reconstructed')
check('cost low  ~0.85', Math.abs(t.cost.low - 0.85) < 0.01, t.cost.low)
check('cost est  ~1.36', Math.abs(t.cost.estimate - 1.36) < 0.01, t.cost.estimate)
check('cost high ~4.25', Math.abs(t.cost.high - 4.25) < 0.01, t.cost.high)
const criticShare = t.byAgent.filter(a=>a.agent.endsWith('-critic')).reduce((n,a)=>n+a.share,0)
check('critics take ~51%', Math.round(criticShare*100) === 51, Math.round(criticShare*100))

const d = discrepancies(state, log)
check('24 vs 25 surfaced', d.length === 1 && d[0].label === 'subagent calls', d)
check('  shows both numbers', d[0]?.values.map(v=>v.value).sort().join() === '24,25,25', d[0]?.values)

check('one disagreement', disagreements(log).length === 1)
check('24 agent calls', agentCalls(log).length === 24)

const merged = deepMerge(base, tiny)
check('tiny overrides chapters to 3', merged.novel.chapters === 3, merged.novel.chapters)
check('tiny keeps base tone', merged.novel.tone === 'hard-scifi', merged.novel.tone)
check('feasibility of tiny is clean', !feasibility(merged).some(c=>c.light==='bad'), feasibility(merged))

const impossible = deepMerge(merged, { novel: { ...merged.novel, words_per_chapter: { min:300, target:5000, max:6000 } } })
check('impossible target caught', feasibility(impossible).some(c=>c.light==='bad'))

const delta = deltaOf(base, merged) as any
check('delta excludes unchanged tone', delta.novel?.tone === undefined, delta.novel)
check('delta includes chapters', delta.novel?.chapters === 3, delta.novel)

// The dev server's allowlist, exercised directly.
//
// `output/../SECURITY.md` once returned 200: it passed the prefix test as
// sent, and only then resolved to the repository root. The check now runs on
// the normalised path, and these cases are here so it stays that way.
const ALLOWED = ['output/', 'config/', 'specs/', '.claude/agents/']
const ROOT = path.resolve(R)
const serves = (requested: string): boolean => {
  const abs = path.resolve(ROOT, requested)
  const inside = abs === ROOT || abs.startsWith(ROOT + path.sep)
  const norm = path.relative(ROOT, abs).split(path.sep).join('/')
  return inside && ALLOWED.some((pre) => norm === pre.slice(0, -1) || norm.startsWith(pre))
}

check('serves a run file', serves('output/deep-space-salvage-derelict/state.json'))
check('serves the flow spec', serves('specs/flow.yaml'))
check('serves an agent definition', serves('.claude/agents/chapter-writer.md'))
check('refuses traversal out of output/', !serves('output/../SECURITY.md'))
check('refuses traversal to .git', !serves('config/../.git/config'))
check('refuses a repo document', !serves('HANDOFF.md'))
check('refuses .claude outside agents/', !serves('.claude/settings.json'))

// --- the annex: the orchestrator is an actor, not a gap ------------------

const critiques = fs
  .readdirSync(`${W}/critiques`)
  .filter((f) => f.endsWith('.json'))
  .map((f) => JSON.parse(fs.readFileSync(`${W}/critiques/${f}`, 'utf8')))

const activity = orchestratorActivity(log, critiques)
check('orchestrator made 5 gate decisions', activity.gateDecisions === 5, activity.gateDecisions)
check('orchestrator arbitrated 1 disagreement', activity.disagreementsArbitrated === 1)
check('orchestrator rejected 1 agent before the gate', activity.preGateRejections === 1, activity.preGateRejections)
check('orchestrator ran length and chatter itself',
  activity.criticsRunLocally.join() === 'chatter,length', activity.criticsRunLocally)
check('orchestrator assembled the book once', activity.assemblies === 1)
check('every non-agent row is attributed to it',
  activity.events === log.length - agentCalls(log).length, activity.events)
check('no log row is dropped',
  log.filter((e) => actorOf(e) === 'orchestrator').length + agentCalls(log).length === log.length)

check('length reproduces', runLocally('length', critiques))
check('chatter reproduces', runLocally('chatter', critiques))
check('continuity does not', !runLocally('continuity', critiques))
check('science does not', !runLocally('science', critiques))

// --- the annex: repair and notes are real fields, and optional ------------

const ch02cont = critiques.find((c: any) => c.chapter === 2 && c.critic === 'continuity')
check('ch02 continuity carries repair', typeof ch02cont.repair === 'string')
const ch01cont = critiques.find((c: any) => c.chapter === 1 && c.critic === 'continuity')
check('ch01 continuity carries notes', Array.isArray(ch01cont.notes) && ch01cont.notes.length > 0)
check('and some critiques carry neither',
  critiques.some((c: any) => !c.repair && !c.notes))

const ch03cont = critiques.find((c: any) => c.chapter === 3 && c.critic === 'continuity')
const overruled = ch03cont.iterations[0].findings.filter((f: any) => f.upheld === false)
check('ch03 draft 1 has exactly 1 overruled finding', overruled.length === 1, overruled.length)
check('  and exactly 1 that reached the writer',
  ch03cont.iterations[0].findings.filter((f: any) => f.upheld !== false).length === 1)

// --- the annex: lines -> configuration, against the real profiles ---------

const tinyDerived = deriveFromLines(60, 64)
check('tiny line band derives near 25-95',
  Math.abs(tinyDerived.lines_per_chapter.min - 25) <= 5 &&
  Math.abs(tinyDerived.lines_per_chapter.max - 95) <= 5, tinyDerived.lines_per_chapter)
check('tiny word target derives within 10% of 420',
  Math.abs(tinyDerived.words_per_chapter.target - 420) / 420 < 0.1,
  tinyDerived.words_per_chapter.target)
const fullDerived = deriveFromLines(250, 84)
check('full word target derives within 10% of 2700',
  Math.abs(fullDerived.words_per_chapter.target - 2700) / 2700 < 0.1,
  fullDerived.words_per_chapter.target)

// --- the annex: the library ----------------------------------------------

const index = JSON.parse(fs.readFileSync(`${R}/output/runs.json`, 'utf8'))
check('manifest lists the run',
  index.runs.length === 1 && index.runs[0].slug === 'deep-space-salvage-derelict')
check('manifest counts 2 retries', index.runs[0].retries === 2, index.runs[0].retries)
check('manifest marks state present', index.runs[0].has_state === true)
check('manifest keeps token provenance', index.runs[0].tokens_source === 'reconstructed')
check('title stands in for a field the data does not have',
  titleFromSlug('deep-space-salvage-derelict') === 'Deep Space Salvage Derelict')
check('a premise slugifies to at most 40 characters',
  slugifyPremise('A deep-space salvage crew finds a derelict that remembers them').length <= 40)

console.log(fails ? `\n${fails} FAILED` : `\nall ${fails === 0 ? 'checks' : ''} passed`)
process.exit(fails ? 1 : 0)
