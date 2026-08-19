import { useState } from 'react'
import type { AgentReport, Run } from '../types'
import { WEAK, failed } from '../types'
import { Panel, Tag } from './Bits'

export default function Traces({ report }: { report: AgentReport }) {
  const [open, setOpen] = useState<string | null>(null)
  const runs = [...report.runs].sort((a, b) => Number(failed(b)) - Number(failed(a)))

  return (
    <Panel
      title={`Runs - ${report.agent}`}
      hint="Every run is a recorded OTel-shaped trace. Failing steps are marked; replaying a run makes no model call."
    >
      <div className="space-y-1.5">
        {runs.map((r) => (
          <div key={r.scenario_id} className="rounded-md" style={{ border: '1px solid var(--line)' }}>
            <button
              className="flex w-full min-w-0 items-center gap-3 px-3 py-2.5 text-left"
              onClick={() => setOpen(open === r.scenario_id ? null : r.scenario_id)}
            >
              <span aria-hidden style={{ color: failed(r) ? 'var(--critical)' : 'var(--good)' }}>
                {failed(r) ? '✕' : '✓'}
              </span>
              <span className="shrink-0 text-sm" style={{ color: 'var(--ink-2)' }}>{r.suite}</span>
              {/* min-w-0 is load-bearing: a flex child will not shrink below its content
                  width without it, and these task strings run to several hundred chars */}
              <span className="min-w-0 flex-1 truncate text-sm">{r.task}</span>
              <span className="shrink-0 text-xs tnum" style={{ color: 'var(--muted)' }}>
                {r.steps} steps
              </span>
              <span aria-hidden style={{ color: 'var(--muted)' }}>
                {open === r.scenario_id ? '−' : '+'}
              </span>
            </button>

            {open === r.scenario_id && <Detail run={r} />}
          </div>
        ))}
      </div>
    </Panel>
  )
}

function Detail({ run }: { run: Run }) {
  return (
    <div className="px-3 pb-3" style={{ borderTop: '1px solid var(--line)' }}>
      {run.findings.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {run.findings.map((f, i) => {
            const weak = WEAK.has(f.code)
            const col = weak ? 'var(--warning)' : 'var(--critical)'
            return (
              <div key={i} className="text-sm">
                <Tag tone={col}>{f.code}{weak ? ' (weak)' : ''}</Tag>
                <span className="ml-2" style={{ color: 'var(--ink-2)' }}>{f.detail}</span>
              </div>
            )
          })}
        </div>
      )}

      <ol className="mt-3 space-y-2">
        {run.steps_detail.map((s) => (
          <li
            key={s.n}
            className="rounded p-2.5 text-xs"
            style={{
              background: s.flagged
                ? 'color-mix(in srgb, var(--critical) 10%, transparent)'
                : 'transparent',
              border: `1px solid ${s.flagged ? 'var(--critical)' : 'var(--line)'}`,
            }}
          >
            <div className="flex items-center gap-2">
              <span className="tnum" style={{ color: 'var(--muted)' }}>step {s.n}</span>
              {s.tool
                ? <Tag tone="var(--s1)">{s.tool}</Tag>
                : <Tag>final answer</Tag>}
              {s.tool && !s.ok && <Tag tone="var(--warning)">tool error</Tag>}
            </div>

            {s.tool && (
              <pre className="mt-1.5 max-w-full overflow-x-auto whitespace-pre-wrap break-words" style={{ color: 'var(--ink-2)' }}>
                {s.tool}({JSON.stringify(s.args)})
              </pre>
            )}
            <p className="mt-1.5 whitespace-pre-wrap" style={{ color: 'var(--ink-2)' }}>
              {s.tool ? s.result : s.reply}
            </p>
          </li>
        ))}
      </ol>

      <p className="mt-2 break-all text-xs" style={{ color: 'var(--muted)' }}>
        trace: {run.trace_file}
      </p>
    </div>
  )
}
