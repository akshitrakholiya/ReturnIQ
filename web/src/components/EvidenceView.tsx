import { BarChart3, ClipboardList, FilePenLine, LineChart, MessageSquareQuote, Search, Tag, X, type LucideIcon } from 'lucide-react'
import type { EvidencePack, EvidenceRef, ToolResult } from '../types'
import { attrLabel, label, pct, when } from './common'

/** What a cited ID means, in words a seller understands. The raw ID stays in the tooltip. */
export function refName(id: string): { icon: LucideIcon; text: string } {
  if (id.startsWith('breakdown:')) {
    const k = id.slice(10)
    const by: Record<string, string> = { root_cause: 'Returns by cause', mismatch: 'Stated vs actual reason',
      media: 'Photo findings', week: 'Returns by week' }
    return { icon: BarChart3, text: by[k] ?? `Returns by ${label(k)}` }
  }
  if (id.startsWith('tool:')) return { icon: Search, text: `Extra lookup ${id.slice(5)}` }
  if (id.startsWith('r_')) return { icon: MessageSquareQuote, text: `Return ${id}` }
  if (id.startsWith('lc_')) return { icon: FilePenLine, text: 'Listing change' }
  if (id === 'metrics') return { icon: LineChart, text: 'Return rate' }
  if (id === 'listing') return { icon: Tag, text: 'Product listing' }
  if (id === 'profile') return { icon: ClipboardList, text: 'Category checklist' }
  return { icon: Tag, text: id }
}

/** A cited source. Click it to see exactly what the AI was looking at. */
export function RefChip({ id, onOpen }: { id: string; onOpen?: (id: string) => void }) {
  const { icon: Icon, text } = refName(id)
  return onOpen
    ? <button type="button" className="chip ref" onClick={() => onOpen(id)} title={`Show the data behind this (${id})`}><Icon size={13} />{text}</button>
    : <span className="chip" title={id}><Icon size={13} />{text}</span>
}

export function EvidenceList({ items, onOpen, counter }: { items: EvidenceRef[]; onOpen: (id: string) => void; counter?: boolean }) {
  return (
    <ul className={`sources ${counter ? 'counter' : ''}`}>
      {items.map((e, i) => <li key={i}><span className="finding">{e.finding}</span><RefChip id={e.ref} onOpen={onOpen} /></li>)}
    </ul>
  )
}

/** {"L":{"length_cm":69}} -> "L: length 69 cm" */
function pretty(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v !== 'object') return String(v)
  if (Array.isArray(v)) return v.map(pretty).join(', ')
  return Object.entries(v as Record<string, unknown>).map(([k, x]) =>
    typeof x === 'object' && x !== null ? `${k}: ${pretty(x)}`
      : `${k.replace(/_cm$/, '').replace(/_/g, ' ')} ${String(x)}${k.endsWith('_cm') ? ' cm' : ''}`).join(' · ')
}

function Rows({ rows, groupBy }: { rows: { group: string; count: number; share?: number; previous_count?: number | null; change?: number | null }[]; groupBy: string }) {
  const max = Math.max(1, ...rows.map((r) => r.count))
  const prev = rows.some((r) => r.previous_count !== null && r.previous_count !== undefined)
  return (
    <table className="bars">
      <thead><tr><th>{label(groupBy)}</th><th>Returns</th>{prev && <th>Before</th>}</tr></thead>
      <tbody>{rows.filter((r) => r.count > 0 || (r.previous_count ?? 0) > 0).map((r) => (
        <tr key={r.group}>
          <td>{label(r.group)}</td>
          <td><div className="hbar"><div style={{ width: `${(r.count / max) * 100}%` }} /><span>{r.count}{r.share !== undefined && r.count > 0 && <small> · {pct(r.share)}</small>}</span></div></td>
          {prev && <td className={r.change && r.change > 0 ? 'up' : ''}>{r.previous_count ?? '—'}{r.change ? <small> ({r.change > 0 ? '+' : ''}{r.change})</small> : null}</td>}
        </tr>))}
      </tbody>
    </table>
  )
}

/** Side panel: resolves a cited ID against the report's evidence pack (or a Q&A lookup). */
export function EvidencePanel({ id, pack, tools, onClose, onOpenReturn }: {
  id: string; pack: EvidencePack | null; tools?: ToolResult[]; onClose: () => void; onOpenReturn?: (id: string) => void
}) {
  let body: React.ReactNode = <p className="muted">This source is not in the saved evidence.</p>
  const b = pack?.breakdowns.find((x) => x.id === id)
  const fb = pack?.feedback.find((x) => x.return_id === id)
  const lc = pack?.listing_changes.find((x) => x.id === id)
  const tool = tools?.find((t) => t.ref_id === id)
  const filterText = (f: Record<string, unknown>) =>
    Object.entries(f).filter(([k]) => k !== 'product_id').map(([k, v]) => `${label(k)}: ${label(String(v))}`).join(', ')
  if (!pack && !tool) body = <p className="muted">Loading…</p>
  else if (b) {
    body = <>
      <p className="muted">Last 90 days{Object.keys(b.filter).length > 0 && <>, only <strong>{filterText(b.filter)}</strong> returns</>}. “Before” is the previous 90 days.</p>
      <Rows rows={b.rows} groupBy={b.group_by} />
    </>
  } else if (tool) {
    const rows = tool.data.rows as { group: string; count: number; share?: number }[] | undefined
    const items = tool.data.items as { return_id: string; comment: string | null }[] | undefined
    body = <>
      <p className="muted">The AI asked for this while working{filterText(tool.args) && <>: <strong>{filterText(tool.args)}</strong></>}.</p>
      {rows ? <Rows rows={rows} groupBy={String(tool.args.group_by ?? 'group')} />
        : items ? <ul className="notes">{items.map((it) => <li key={it.return_id}><strong>{it.return_id}</strong> “{it.comment}”</li>)}</ul>
        : <pre className="json">{JSON.stringify(tool.data, null, 2)}</pre>}
    </>
  } else if (fb || id.startsWith('r_')) {
    body = <>
      {fb ? <>
        {fb.comment && <blockquote>“{fb.comment}”</blockquote>}
        <dl className="kv">
          <dt>Customer chose</dt><dd>{label(fb.stated_reason)}</dd>
          <dt>Actual cause</dt><dd>{fb.cause ? label(fb.cause) : '—'} {fb.reviewed ? <span className="badge status-reviewed">confirmed by reviewer</span> : <span className="badge status-awaiting_review">AI only</span>}</dd>
          {fb.reviewer_note && <><dt>Reviewer note</dt><dd>{fb.reviewer_note}</dd></>}
          {fb.media_finding && <><dt>Photo shows</dt><dd>{label(fb.media_finding)}</dd></>}
          {Object.keys(fb.variant).length > 0 && <><dt>Ordered</dt><dd>{Object.entries(fb.variant).map(([k, v]) => `${k} ${v}`).join(', ')}</dd></>}
        </dl></> : <p className="muted">A return the AI found through an extra lookup.</p>}
      {onOpenReturn && <button className="secondary" onClick={() => onOpenReturn(id)}>Open this return →</button>}
    </>
  } else if (lc) {
    body = <dl className="kv">
      <dt>What changed</dt><dd>{attrLabel(lc.field)}</dd>
      <dt>Before</dt><dd>{pretty(lc.old_value)}</dd><dt>After</dt><dd><strong>{pretty(lc.new_value)}</strong></dd>
      <dt>When</dt><dd>{when(lc.changed_at)}</dd>
    </dl>
  } else if (pack && id === 'metrics') {
    const m = pack.metrics
    body = <dl className="kv">
      <dt>Orders</dt><dd>{m.orders}</dd><dt>Returns</dt><dd>{m.returns}</dd>
      <dt>Return rate</dt><dd>{pct(m.return_rate)}{m.previous_return_rate !== null && <> (before: {pct(m.previous_return_rate)})</>}</dd>
      <dt>Category average</dt><dd>{pct(m.category_rate)}</dd><dt>Trend</dt><dd>{m.trend}</dd>
    </dl>
  } else if (pack && id === 'listing') {
    body = <><p><strong>{pack.listing.title}</strong></p><p>{pack.listing.description}</p>
      <dl className="kv">{Object.entries(pack.listing.attributes).flatMap(([k, v]) => [<dt key={`${k}-t`}>{label(k)}</dt>, <dd key={`${k}-d`}>{pretty(v)}</dd>])}</dl></>
  } else if (pack && id === 'profile') {
    body = <dl className="kv">
      <dt>Category</dt><dd>{label(pack.profile.category)}</dd><dt>Variants</dt><dd>{pack.profile.variant_dimensions.join(', ')}</dd>
      <dt>Checked</dt><dd>{pack.profile.listing_checks.join('; ')}</dd>
    </dl>
  }
  const { icon: Icon, text } = refName(id)
  return (
    <aside className="panel" role="dialog" aria-label={text}>
      <div className="panel-head"><h3><Icon size={16} />{text}</h3>
        <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={16} /></button></div>
      {body}
      <p className="muted tiny">Source ID: <code>{id}</code></p>
    </aside>
  )
}
