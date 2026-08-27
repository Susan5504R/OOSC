import { useState } from 'react'
import type { AgentReport } from '../types'
import { Panel } from './Bits'

/* The find -> fix -> prove loop.
 *
 * Every other panel on this page diagnoses. This one prescribes: the rules Crucible derived
 * from what actually broke, priced by what fixing each is worth, with the evidence that
 * produced them. Written with zero model calls, same as the score.
 *
 * `worth` is a Shapley share, not a leave-one-out delta. Per-run penalties saturate at 1.0,
 * so leave-one-out prices the worst failure lowest - see crucible/patching/__init__.py.
 */
export default function PatchPanel({ report, patched }: {
  report: AgentReport
  patched?: AgentReport
}) {
  const patch = report.patch
  const [open, setOpen] = useState<string | null>(null)
  if (!patch?.clauses?.length) return null

  const headroom = +(patch.ceiling - patch.base_score).toFixed(1)
  const measured = patched ? +(patched.scorecard.score - patch.base_score).toFixed(1) : null
  const top = Math.max(...patch.clauses.map((c) => c.score_gain), 1)

  return (
    <Panel
      title="Generated fix"
      hint={`Crucible read ${report.agent}'s own failures and wrote the rules that would have prevented them, ranked by what fixing each one is worth. No model call.`}
    >
      {measured !== null && patched && (
        <div className="mb-4 flex flex-wrap items-stretch gap-2">
          <Step
            label="found"
            value={patch.base_score.toFixed(1)}
            sub={report.agent}
            tone="critical"
          />
          <Arrow />
          <Step
            label="fix"
            value={`${patch.clauses.length}`}
            sub="rules written, 0 model calls"
            tone="warning"
          />
          <Arrow />
          <Step
            label="proved"
            value={patched.scorecard.score.toFixed(1)}
            sub={`${measured > 0 ? '+' : ''}${measured} measured, re-run`}
            tone={measured > 0 ? 'good' : 'critical'}
          />
        </div>
      )}

      <div className="space-y-1.5">
        {patch.clauses.map((c) => (
          <div key={c.code} className="rounded-md" style={{ border: '1px solid var(--line)' }}>
            <button
              className="flex w-full min-w-0 items-center gap-3 px-3 py-2.5 text-left"
              onClick={() => setOpen(open === c.code ? null : c.code)}
            >
              <span className="shrink-0 text-sm tnum" style={{ color: 'var(--s2)' }}>
                +{c.score_gain.toFixed(1)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm">{c.code}</span>
                {/* bar is redundant with the number on purpose - it makes the ranking
                    readable at a glance from across a room during a live demo */}
                <span
                  aria-hidden
                  className="mt-1 block h-1 rounded"
                  style={{
                    width: `${Math.max(4, (c.score_gain / top) * 100)}%`,
                    background: 'var(--s2)',
                  }}
                />
              </span>
              <span className="shrink-0 text-xs tnum" style={{ color: 'var(--muted)' }}>
                {c.runs_hit} runs
              </span>
              <span aria-hidden style={{ color: 'var(--muted)' }}>
                {open === c.code ? '−' : '+'}
              </span>
            </button>

            {open === c.code && (
              <div className="px-3 pb-3" style={{ borderTop: '1px solid var(--line)' }}>
                <p className="mt-3 text-sm" style={{ color: 'var(--ink)' }}>{c.text}</p>
                <div className="mt-2 text-xs uppercase tracking-wide"
                     style={{ color: 'var(--muted)' }}>
                  evidence
                </div>
                <ul className="mt-1 space-y-1">
                  {c.evidence.map((e, i) => (
                    <li key={i} className="text-xs" style={{ color: 'var(--ink-2)' }}>{e}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ))}
      </div>

      <p className="mt-4 text-xs" style={{ color: 'var(--muted)' }}>
        Worth is each rule&rsquo;s Shapley share of the {headroom} points between the measured{' '}
        {patch.base_score} and the {patch.ceiling} ceiling. The ceiling assumes every one of
        these stops firing completely, so it is a bound, not a forecast
        {measured !== null && patched
          ? ` — re-running the patched agent actually scored ${patched.scorecard.score}.`
          : '.'}
      </p>
    </Panel>
  )
}

function Step({ label, value, sub, tone }: {
  label: string; value: string; sub: string; tone: 'good' | 'critical' | 'warning'
}) {
  return (
    <div className="flex-1 rounded-md p-3" style={{ border: '1px solid var(--line)' }}>
      <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
        {label}
      </div>
      <div className="mt-0.5 text-2xl tnum" style={{ color: `var(--${tone})` }}>{value}</div>
      <div className="mt-0.5 text-xs" style={{ color: 'var(--ink-2)' }}>{sub}</div>
    </div>
  )
}

const Arrow = () => (
  <div aria-hidden className="flex items-center text-lg" style={{ color: 'var(--muted)' }}>→</div>
)
