import type { ReactNode } from 'react'
import type { Status } from '../types'

// Plain-language names for the codes the API uses; anything else falls back to "snake case" -> "snake case".
const NAMES: Record<string, string> = {
  size_fit: 'Size / fit', defect_quality: 'Defect / quality', damaged_in_transit: 'Damaged in transit',
  wrong_item: 'Wrong item', not_as_described: 'Not as described', changed_mind: 'Changed mind',
  suspicious: 'Suspicious', other: 'Other',
  pending_analysis: 'waiting for AI', analyzing: 'AI analyzing', awaiting_review: 'needs review',
  reviewed: 'reviewed', analysis_failed: 'AI failed',
  approve_return: 'Approve the return', request_more_evidence: 'Ask for more evidence',
  reject_return: 'Reject the return', manual_review: 'Check manually',
  not_enough_data: 'Not enough data', healthy: 'Looks healthy', analyzed: 'Problems found',
  media_finding: 'photo finding', reason_mismatch: 'stated vs actual reason', root_cause: 'cause',
  no_photo_finding: 'no photo', no_issue_visible: 'no issue visible', not_analyzed: 'not analyzed yet',
  stated_matches_actual: 'reason matches', last_90d: 'last 90 days', last_30d: 'last 30 days',
  electronics_accessories: 'Electronics accessories', apparel: 'Apparel', footwear: 'Footwear',
}
export const label = (s: string) => NAMES[s] ?? s.replace(/_/g, ' ')

/** "attributes.size_chart.length_cm" -> "size chart length" */
export const attrLabel = (s: string) =>
  s.replace(/^attributes\./, '').replace(/_cm\b/, '').replace(/[._]/g, ' ').trim()

/** "WOMEN Graphic_Tees (Var 01)" -> "Women Graphic Tees (Var 01)" */
export const productName = (s: string) =>
  s.replace(/_/g, ' ').replace(/\b(MEN|WOMEN)\b/g, (w) => w[0] + w.slice(1).toLowerCase())

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`badge status-${status}`}>{label(status)}</span>
}

export function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const tone = value >= 0.75 ? 'good' : value >= 0.6 ? 'mid' : 'low'
  return (
    <div className="conf" title={`${pct}%`}>
      <div className="conf-track"><div className={`conf-bar ${tone}`} style={{ width: `${pct}%` }} /></div>
      <span>{pct}%</span>
    </div>
  )
}

/** The brand mark: a small reticle, in gold. */
export function Mark({ size = 30 }: { size?: number }) {
  return (
    <svg className="mark" width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <path d="M11.5 12.5 9 4.5l8 4M36.5 12.5 39 4.5l-8 4" /><circle cx="24" cy="26" r="15" /><circle className="core" cx="24" cy="26" r="3.5" />
    </svg>
  )
}

/** Editorial page header: machine-register eyebrow, serif title with an italic key term, optional actions. */
export function PageHead({ index, module, title, em, children, lede }: {
  index: string; module: string; title: string; em?: string; lede?: ReactNode; children?: ReactNode
}) {
  return (
    <header className="page-head">
      <div>
        <div className="mono-label eyebrow"><span>{index}</span> / {module}</div>
        <h1>{title}{em && <> <em>{em}</em></>}</h1>
        {lede && <p className="lede">{lede}</p>}
      </div>
      {children && <div className="head-actions">{children}</div>}
    </header>
  )
}

/** Folio heading used inside panels: mono index + label, with a hairline rule. */
export function Folio({ n, children, aside }: { n?: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="folio"><span>{n && <b>[{n}]</b>} {children}</span>{aside && <span className="folio-aside">{aside}</span>}</div>
  )
}

export const money = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
export const pct = (n: number) => `${Math.round(n * 1000) / 10}%`

/** "16 Oct, 12:42 am" (adds the year only when it is not this year) */
export function when(iso: string) {
  const d = new Date(iso)
  const sameYear = d.getFullYear() === new Date().getFullYear()
  return d.toLocaleString('en-IN', { day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }),
    hour: 'numeric', minute: '2-digit' })
}

/** "5 min ago", falling back to the date */
export function ago(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return when(iso)
}

export function ErrorBox({ error }: { error: string | null }) {
  return error ? <div className="error">{error}</div> : null
}
