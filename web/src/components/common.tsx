import type { Status } from '../types'

export const label = (s: string) => s.replace(/_/g, ' ')

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`badge status-${status}`}>{label(status)}</span>
}

export function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const tone = value >= 0.75 ? 'good' : value >= 0.6 ? 'mid' : 'low'
  return (
    <div className="conf" title={`${pct}%`}>
      <div className={`conf-bar ${tone}`} style={{ width: `${pct}%` }} />
      <span>{pct}%</span>
    </div>
  )
}

export const money = (n: number) => `₹${n.toLocaleString('en-IN')}`
export const when = (iso: string) => new Date(iso).toLocaleString()

export function ErrorBox({ error }: { error: string | null }) {
  return error ? <div className="error">{error}</div> : null
}
