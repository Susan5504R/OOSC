import { useEffect, useMemo, useState } from 'react'
import type { AgentReport, Bundle } from './types'
import { Panel, Tile } from './components/Bits'
import Ladder from './components/Ladder'
import Injection from './components/Injection'
import Taxonomy from './components/Taxonomy'
import Traces from './components/Traces'

// families are the regression story: baseline vs hardened build of the same agent
const family = (name: string) => name.split('@')[0]

export default function App() {
  const [data, setData] = useState<Bundle | null>(null)
  const [err, setErr] = useState('')
  const [fam, setFam] = useState('devops')
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/report.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setData)
      .catch((e) => setErr(String(e)))
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  const fams = useMemo(
    () => [...new Set((data?.agents ?? []).map((a) => family(a.agent)))],
    [data],
  )
  const reports = useMemo<AgentReport[]>(
    () => (data?.agents ?? []).filter((a) => family(a.agent) === fam)
      .sort((a, b) => a.agent.localeCompare(b.agent)),
    [data, fam],
  )

  if (err) return <Shell><p style={{ color: 'var(--critical)' }}>Failed to load report.json - {err}</p></Shell>
  if (!data) return <Shell><p style={{ color: 'var(--muted)' }}>Loading…</p></Shell>
  if (!reports.length) return <Shell><p>No reports.</p></Shell>

  const [base, head] = reports          // v1 then v2
  const delta = head ? +(head.scorecard.score - base.scorecard.score).toFixed(1) : 0

  return (
    <Shell>
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Crucible</h1>
          <p className="mt-1 text-sm" style={{ color: 'var(--ink-2)' }}>
            Agent evaluation and reliability engine — continuous integration for autonomous
            agents.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {fams.length > 1 && (
            <select
              value={fam} onChange={(e) => setFam(e.target.value)}
              className="rounded-md px-2.5 py-1.5 text-sm"
              style={{ background: 'var(--surface)', color: 'var(--ink)', border: '1px solid var(--line)' }}
            >
              {fams.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          )}
          <button
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            className="rounded-md px-2.5 py-1.5 text-sm"
            style={{ background: 'var(--surface)', color: 'var(--ink-2)', border: '1px solid var(--line)' }}
          >
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
        </div>
      </header>

      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          label="Reliability score"
          value={`${base.scorecard.score}`}
          sub={`${base.agent} · ${base.scorecard.runs} scenarios`}
          tone={base.scorecard.score < 60 ? 'critical' : 'good'}
        />
        {head && (
          <Tile
            label="Hardened build"
            value={`${head.scorecard.score}`}
            sub={`${head.agent} · ${delta > 0 ? '+' : ''}${delta} vs baseline`}
            tone={head.scorecard.score < 60 ? 'critical' : 'good'}
          />
        )}
        <Tile
          label="Guardrail break point"
          value={base.scorecard.break_label.split(' ')[0]}
          sub={`${base.agent} fires the irreversible tool here`}
          tone={base.scorecard.guardrail_break_point >= 5 ? 'good' : 'critical'}
        />
        <Tile
          label="Model calls to score"
          value="0"
          sub="every failure mode is detected from the trace"
          tone="good"
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Ladder reports={reports} />
        <Injection reports={reports} />
        <Taxonomy reports={reports} />
        <Panel
          title="Regression gate"
          hint="crucible ci exits non-zero when a build regresses. It runs off recorded traces, so CI needs no API key and no secrets."
        >
          <table className="w-full text-sm">
            <tbody>
              {reports.map((r) => (
                <tr key={r.agent} style={{ borderTop: '1px solid var(--line)' }}>
                  <td className="py-2">{r.agent}</td>
                  <td className="py-2 tnum">{r.scorecard.score}</td>
                  <td className="py-2 tnum" style={{ color: 'var(--ink-2)' }}>
                    pass {(r.scorecard.pass_rate * 100).toFixed(0)}%
                  </td>
                  <td className="py-2 text-right" style={{ color: 'var(--ink-2)' }}>
                    {r.scorecard.break_label}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {head && (
            <p className="mt-4 text-sm" style={{ color: delta >= 0 ? 'var(--good)' : 'var(--critical)' }}>
              {delta >= 0 ? '✓' : '✕'} {base.agent} → {head.agent}: {delta > 0 ? '+' : ''}{delta} points
              {delta < 0 && ' — gate blocks this build'}
            </p>
          )}
        </Panel>
      </div>

      <div className="mt-5 grid gap-5">
        {reports.map((r) => <Traces key={r.agent} report={r} />)}
      </div>

      <footer className="mt-8 text-xs" style={{ color: 'var(--muted)' }}>
        Traces are OTel-shaped spans following the GenAI semantic conventions; OTLP export is
        a thin adapter. Replay is deterministic — live model runs are not, which is precisely
        why replay exists.
      </footer>
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto max-w-6xl overflow-x-hidden p-6">{children}</main>
}
