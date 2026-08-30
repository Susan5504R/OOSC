import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AgentReport, Finding, Run, Step } from '../types'
import { WEAK, failed } from '../types'
import { Tag } from './Bits'

/* Replay Theater.
 *
 * The tables elsewhere on this page tell you an agent scored 42.4. They do not make you
 * feel it. This plays a single recorded run back one step at a time - the model's reply,
 * then the tool it reached for, then what that did to the sandbox - so the moment a
 * production table disappears is something you watch rather than read.
 *
 * Everything here comes from steps_detail in the committed report. No model call, no
 * backend, and the run is byte-identical every time it is played.
 */

const BEAT = 1500 // ms per step at 1x - slow enough to read a tool call out loud

// Ordered worst-first: the headline finding for a step should be the scariest one.
const SEVERITY = [
  'DESTRUCTIVE_ACTION',
  'UNSAFE_ESCALATION',
  'INJECTION_COMPLIANCE',
  'OVERCONFIDENCE',
  'GOAL_DRIFT',
  'SILENT_FAILURE',
  'HALLUCINATED_TOOL',
  'TOOL_LOOP',
  'PARAM_FABRICATION',
  'BUDGET_EXHAUSTION',
]

const rank = (c: string) => {
  const i = SEVERITY.indexOf(c)
  return i < 0 ? SEVERITY.length : i
}

/* The most demonstrative run in the report: prefer a real failure, at the lowest pressure
   it happened, carrying the most severe finding. A break at L0 is a far better opening
   shot than the same break at L4 - nobody pushed it. */
function headline(runs: Run[]): Run | undefined {
  const bad = runs.filter(failed)
  if (!bad.length) return runs[0]
  return [...bad].sort((a, b) => {
    const sa = Math.min(...a.findings.filter((f) => !WEAK.has(f.code)).map((f) => rank(f.code)))
    const sb = Math.min(...b.findings.filter((f) => !WEAK.has(f.code)).map((f) => rank(f.code)))
    return sa - sb || a.pressure - b.pressure
  })[0]
}

const worldOf = (r: Run, upto: number) => {
  for (let i = upto; i >= 0; i--) {
    const w = r.steps_detail[i]?.world
    if (w && Object.keys(w).length) return w
  }
  return undefined
}

export default function Theater({ reports }: { reports: AgentReport[] }) {
  const runs = useMemo(() => reports.flatMap((r) => r.runs), [reports])
  const [pick, setPick] = useState<string>('')
  const run = useMemo(
    () => runs.find((r) => r.run_id === pick) ?? headline(runs),
    [runs, pick],
  )

  const total = run?.steps_detail.length ?? 0
  const [at, setAt] = useState(0)          // how many steps are revealed
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const liveRef = useRef<HTMLDivElement>(null)

  // a different run restarts the playback rather than stranding the cursor past the end
  useEffect(() => { setAt(0); setPlaying(false) }, [run?.run_id])

  useEffect(() => {
    if (!playing || at >= total) return
    const t = setTimeout(() => setAt((n) => n + 1), BEAT / speed)
    return () => clearTimeout(t)
  }, [playing, at, total, speed])

  useEffect(() => {
    if (at >= total) setPlaying(false)
  }, [at, total])

  // keep the newest step in view while playing, without yanking the whole page around
  useEffect(() => {
    if (at > 0 && playing) {
      liveRef.current?.scrollTo({ top: liveRef.current.scrollHeight, behavior: 'smooth' })
    }
  }, [at, playing])

  const start = useCallback(() => {
    if (at >= total) setAt(0)
    setPlaying(true)
  }, [at, total])

  if (!run) return null

  const shown = run.steps_detail.slice(0, at)
  const hard = run.findings.filter((f) => !WEAK.has(f.code))
  const done = at >= total
  const world = worldOf(run, at - 1)

  return (
    <section className="card overflow-hidden">
      <div
        className="flex flex-wrap items-center justify-between gap-3 px-5 py-4"
        style={{ borderBottom: '1px solid var(--line)' }}
      >
        <div className="min-w-0">
          <h2 className="text-base font-semibold">Replay Theater</h2>
          <p className="mt-1 text-sm" style={{ color: 'var(--ink-2)' }}>
            One recorded run, played back step by step. Identical every time — no model call.
          </p>
        </div>
        <select
          value={run.run_id}
          onChange={(e) => setPick(e.target.value)}
          className="max-w-full rounded-md px-2.5 py-1.5 text-sm"
          style={{ background: 'var(--plane)', color: 'var(--ink)', border: '1px solid var(--line)' }}
        >
          {runs.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {failed(r) ? '✕' : '✓'} {r.agent} · {r.suite}
              {r.suite === 'ladder' ? ` L${r.pressure}` : ''}
              {r.payload_cls ? ` · ${r.payload_cls}` : ''}
            </option>
          ))}
        </select>
      </div>

      <div className="px-5 py-3" style={{ borderBottom: '1px solid var(--line)' }}>
        <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
          the request
        </div>
        <p className="mt-1 text-sm" style={{ color: 'var(--ink-2)' }}>“{run.task}”</p>
      </div>

      <div className="flex flex-wrap items-center gap-3 px-5 py-3"
           style={{ borderBottom: '1px solid var(--line)' }}>
        <button
          onClick={() => (playing ? setPlaying(false) : start())}
          className="rounded-md px-3 py-1.5 text-sm font-medium"
          style={{ background: 'var(--s1)', color: '#fff' }}
        >
          {playing ? '❚❚ Pause' : at >= total ? '↻ Replay' : '▶ Play'}
        </button>

        <input
          type="range" min={0} max={total} value={at} aria-label="step"
          onChange={(e) => { setPlaying(false); setAt(+e.target.value) }}
          className="min-w-32 flex-1"
        />

        <span className="text-sm tnum shrink-0" style={{ color: 'var(--ink-2)' }}>
          step {at}/{total}
        </span>

        {[1, 2, 4].map((s) => (
          <button
            key={s} onClick={() => setSpeed(s)}
            className="rounded px-2 py-1 text-xs tnum"
            style={{
              color: speed === s ? 'var(--ink)' : 'var(--muted)',
              border: `1px solid ${speed === s ? 'var(--s1)' : 'var(--line)'}`,
            }}
          >
            {s}×
          </button>
        ))}
      </div>

      <div className="grid gap-0 lg:grid-cols-[1fr_260px]">
        <div ref={liveRef} className="max-h-[26rem] overflow-y-auto px-5 py-4">
          {at === 0 && (
            <p className="py-10 text-center text-sm" style={{ color: 'var(--muted)' }}>
              Press play to watch this run unfold.
            </p>
          )}
          <ol className="space-y-3">
            {shown.map((s) => (
              <StepCard key={s.n} step={s} findings={hard.filter((f) => f.step === s.n)} />
            ))}
          </ol>

          {done && (
            <div
              className="mt-4 rounded-md p-3 text-sm"
              style={{
                border: `1px solid ${hard.length ? 'var(--critical)' : 'var(--good)'}`,
                color: hard.length ? 'var(--critical)' : 'var(--good)',
              }}
            >
              {hard.length
                ? `Run failed — ${hard.map((f) => f.code).join(', ')}`
                : 'Run passed — no failure mode detected'}
            </div>
          )}
        </div>

        <WorldPane world={world} prev={worldOf(run, at - 2)} />
      </div>
    </section>
  )
}

function StepCard({ step, findings }: { step: Step; findings: Finding[] }) {
  const bad = findings.length > 0
  return (
    <li
      className="rounded-md p-3"
      style={{
        border: `1px solid ${bad ? 'var(--critical)' : 'var(--line)'}`,
        background: bad ? 'color-mix(in srgb, var(--critical) 10%, transparent)' : 'transparent',
      }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs tnum" style={{ color: 'var(--muted)' }}>step {step.n}</span>
        {step.tool
          ? <Tag tone={bad ? 'var(--critical)' : 'var(--s1)'}>{step.tool}</Tag>
          : <Tag>final answer</Tag>}
        {step.tool && !step.ok && <Tag tone="var(--warning)">tool error</Tag>}
      </div>

      {step.tool && (
        <pre
          className="mt-2 overflow-x-auto whitespace-pre-wrap break-words text-xs"
          style={{ color: bad ? 'var(--critical)' : 'var(--ink-2)' }}
        >
          {step.tool}({JSON.stringify(step.args)})
        </pre>
      )}

      <p className="mt-2 whitespace-pre-wrap text-xs" style={{ color: 'var(--ink-2)' }}>
        {step.tool ? step.result : step.reply}
      </p>

      {findings.map((f, i) => (
        <div key={i} className="mt-2 text-xs">
          <Tag tone="var(--critical)">{f.code}</Tag>
          <span className="ml-2" style={{ color: 'var(--ink-2)' }}>{f.detail}</span>
        </div>
      ))}
    </li>
  )
}

const asList = (v: unknown): string[] => {
  if (Array.isArray(v)) return v.map((x) => String(x))
  // k=v, not just the keys: "worker=degraded" is the interesting half of a services map
  if (v && typeof v === 'object') {
    return Object.entries(v as Record<string, unknown>).map(([k, x]) =>
      x && typeof x === 'object' ? k : `${k}=${x}`)
  }
  return [String(v)]
}

/* The sandbox as the agent leaves it, with what just changed called out.
 *
 * Watching `events` get struck out of this list the instant drop_table fires is the whole
 * point of playing a run back instead of tabulating it - it needs no narration. */
function WorldPane({ world, prev }: {
  world?: Record<string, unknown>
  prev?: Record<string, unknown>
}) {
  return (
    <div className="px-5 py-4 lg:border-l" style={{ borderColor: 'var(--line)' }}>
      <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
        sandbox state
      </div>
      {!world && (
        <p className="mt-2 text-xs" style={{ color: 'var(--muted)' }}>
          Starts when the run does.
        </p>
      )}
      <dl className="mt-2 space-y-2">
        {world && Object.entries(world).map(([k, v]) => {
          const now = asList(v)
          const before = prev ? asList(prev[k] ?? []) : now
          const gone = before.filter((x) => !now.includes(x))
          const added = now.filter((x) => !before.includes(x))
          return (
            <div key={k}>
              <dt className="text-xs" style={{ color: 'var(--muted)' }}>{k}</dt>
              <dd className="text-xs break-words" style={{ color: 'var(--ink-2)' }}>
                {!now.length && !gone.length && '—'}
                {/* additions get the "changed" accent, never green: an entry landing in a
                    `dropped` list is a change, and reading it as good would invert it */}
                {now.map((x) => (
                  <span key={x} className="mr-1.5"
                        style={added.includes(x) ? { color: 'var(--s2)' } : undefined}>
                    {x}
                  </span>
                ))}
                {gone.map((x) => (
                  <span key={x} className="mr-1.5 line-through"
                        style={{ color: 'var(--critical)' }}>
                    {x}
                  </span>
                ))}
              </dd>
            </div>
          )
        })}
      </dl>
    </div>
  )
}
