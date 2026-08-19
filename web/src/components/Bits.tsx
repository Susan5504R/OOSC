import type { ReactNode } from 'react'

export function Tile({ label, value, sub, tone }: {
  label: string
  value: ReactNode
  sub?: string
  tone?: 'good' | 'critical' | 'warning'
}) {
  const col = tone ? `var(--${tone})` : 'var(--ink)'
  return (
    <div className="card p-4">
      <div className="text-xs uppercase tracking-wide" style={{ color: 'var(--muted)' }}>
        {label}
      </div>
      <div className="mt-1 text-3xl tnum" style={{ color: col }}>{value}</div>
      {sub && <div className="mt-1 text-sm" style={{ color: 'var(--ink-2)' }}>{sub}</div>}
    </div>
  )
}

export function Panel({ title, hint, children }: {
  title: string
  hint?: string
  children: ReactNode
}) {
  return (
    <section className="card p-5">
      <h2 className="text-base font-semibold">{title}</h2>
      {hint && <p className="mt-1 text-sm" style={{ color: 'var(--ink-2)' }}>{hint}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

/* Status is never carried by colour alone - every state ships an icon and a word. */
export function Status({ ok, yes, no }: { ok: boolean; yes: string; no: string }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 text-sm font-medium"
      style={{ color: ok ? 'var(--good)' : 'var(--critical)' }}
    >
      <span aria-hidden>{ok ? '✓' : '✕'}</span>
      {ok ? yes : no}
    </span>
  )
}

export function Tag({ children, tone }: { children: ReactNode; tone?: string }) {
  return (
    <span
      className="rounded px-1.5 py-0.5 text-xs"
      style={{
        color: tone ?? 'var(--ink-2)',
        border: `1px solid ${tone ?? 'var(--line)'}`,
      }}
    >
      {children}
    </span>
  )
}
