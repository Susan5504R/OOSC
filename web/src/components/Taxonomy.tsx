import {
  Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import type { AgentReport } from '../types'
import { SAFETY } from '../types'
import { Panel } from './Bits'

const ORDER = [
  'DESTRUCTIVE_ACTION', 'UNSAFE_ESCALATION', 'INJECTION_COMPLIANCE',
  'OVERCONFIDENCE', 'GOAL_DRIFT', 'SILENT_FAILURE', 'HALLUCINATED_TOOL',
  'TOOL_LOOP', 'PARAM_FABRICATION', 'BUDGET_EXHAUSTION',
]

export default function Taxonomy({ reports }: { reports: AgentReport[] }) {
  const [a, b] = reports
  const rows = ORDER
    .map((code) => ({
      code,
      safety: SAFETY.has(code),
      [a.agent]: Math.round((a.scorecard.failure_rates[code] ?? 0) * 100),
      [b.agent]: Math.round((b?.scorecard.failure_rates[code] ?? 0) * 100),
    }))
    .filter((r) => (r[a.agent] as number) > 0 || (r[b?.agent] as number) > 0)

  if (!rows.length) {
    return (
      <Panel title="Failure taxonomy">
        <p className="text-sm" style={{ color: 'var(--ink-2)' }}>No failures recorded.</p>
      </Panel>
    )
  }

  return (
    <Panel
      title="Failure taxonomy"
      hint="Share of runs tripping each failure mode. Every one of these is detected from the recorded trace - scoring costs zero model calls."
    >
      <div style={{ height: rows.length * 46 + 60 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 44, top: 4 }}
                    barGap={2} barCategoryGap={14}>
            <CartesianGrid horizontal={false} stroke="var(--grid)" />
            <XAxis type="number" domain={[0, 100]} unit="%" stroke="var(--muted)"
                   tick={{ fill: 'var(--muted)', fontSize: 12 }} tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey="code" width={168} stroke="var(--muted)"
                   tick={{ fill: 'var(--ink-2)', fontSize: 11 }} tickLine={false} axisLine={false} />
            <Tooltip
              cursor={{ fill: 'var(--grid)', opacity: 0.35 }}
              contentStyle={{
                background: 'var(--surface)', border: '1px solid var(--line)',
                borderRadius: 8, color: 'var(--ink)', fontSize: 12,
              }}
              formatter={(v) => [`${Number(v)}% of runs`, '']}
            />
            <Legend wrapperStyle={{ fontSize: 12, color: 'var(--ink-2)' }} />
            <Bar dataKey={a.agent} fill="var(--s1)" radius={[0, 4, 4, 0]} barSize={11}>
              <LabelList dataKey={a.agent} position="right"
                         formatter={(v) => (Number(v) ? `${Number(v)}%` : '')}
                         style={{ fill: 'var(--ink-2)', fontSize: 11 }} />
              {rows.map((r) => <Cell key={r.code} />)}
            </Bar>
            {b && (
              <Bar dataKey={b.agent} fill="var(--s2)" radius={[0, 4, 4, 0]} barSize={11}>
                <LabelList dataKey={b.agent} position="right"
                           formatter={(v) => (Number(v) ? `${Number(v)}%` : '')}
                           style={{ fill: 'var(--ink-2)', fontSize: 11 }} />
              </Bar>
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <p className="mt-3 text-xs" style={{ color: 'var(--muted)' }}>
        Safety modes ({[...SAFETY].join(', ')}) carry the heaviest weight in the reliability
        score.
      </p>
    </Panel>
  )
}
