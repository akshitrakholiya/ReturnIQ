import { useEffect, useState } from 'react'
import { api } from '../api'
import { usePolling } from '../usePolling'
import type { Cause, QueueItem } from '../types'
import { CAUSES } from '../types'
import { Confidence, ErrorBox, StatusBadge, label, when } from './common'
import { ListingGallery, MediaGallery } from './MediaGallery'
import { VerdictView } from './VerdictView'

const FILTERS = [
  { key: 'awaiting_review', name: 'Needs review' },
  { key: 'pending_analysis', name: 'Pending' },
  { key: 'analyzing', name: 'Analyzing' },
  { key: 'reviewed', name: 'Reviewed' },
  { key: '', name: 'All' },
]

function Queue({ onOpen }: { onOpen: (id: string) => void }) {
  const [filter, setFilter] = useState('awaiting_review')
  const [items, setItems] = useState<QueueItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => { api.queue(filter || undefined).then((r) => { setItems(r); setError(null) }).catch((e) => setError(String(e))) }, [filter, tick])
  return (
    <div className="card">
      <div className="row between">
        <h2>Reviewer queue</h2>
        <button className="secondary" onClick={() => setTick((t) => t + 1)}>Refresh</button>
      </div>
      <div className="tabs small">{FILTERS.map((f) => (
        <button key={f.key} className={filter === f.key ? 'active' : ''} onClick={() => setFilter(f.key)}>{f.name}</button>))}</div>
      <p className="muted">“Needs review” also lists returns whose AI analysis failed.</p>
      <ErrorBox error={error} />
      <table className="clickable">
        <thead><tr><th>Return</th><th>Product</th><th>Status</th><th>Customer said</th><th>AI says</th><th>Confidence</th><th>Media</th><th>Created</th></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id} onClick={() => onOpen(r.id)}>
              <td><code>{r.id}</code></td><td>{r.product_name}</td><td><StatusBadge status={r.status} /></td>
              <td>{label(r.stated_reason)}</td>
              <td>{r.ai_root_cause ? <>{label(r.ai_root_cause)}{r.ai_root_cause !== r.stated_reason && <span className="mismatch" title="mismatch"> ≠</span>}</> : '—'}</td>
              <td>{r.confidence !== null ? <Confidence value={r.confidence} /> : '—'}</td>
              <td>{r.media_count}</td><td>{when(r.created_at)}</td>
            </tr>
          ))}
          {items.length === 0 && <tr><td colSpan={8} className="muted">Nothing here.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

function ReviewScreen({ id, onBack }: { id: string; onBack: () => void }) {
  const [runKey, setRunKey] = useState(0) // bumped when the reviewer starts an analysis, to restart polling
  const { data, error, setData } = usePolling(
    () => api.detail(id),
    (d) => !(d.status === 'analyzing' || (d.status === 'pending_analysis' && runKey > 0)),
    2500, [id, runKey])
  const [decision, setDecision] = useState<'accepted' | 'rejected'>('accepted')
  const [cause, setCause] = useState<Cause>('other')
  const [note, setNote] = useState('')
  const [reviewer, setReviewer] = useState(() => localStorage.getItem('reviewer') ?? '')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  const ai = data?.analysis?.root_cause
  useEffect(() => { if (ai) setCause(CAUSES.find((c) => c !== ai && c !== 'suspicious') ?? 'other') }, [ai])

  if (!data) return <div className="card"><button className="secondary" onClick={onBack}>← Queue</button><p>Loading…</p><ErrorBox error={error} /></div>

  const refresh = async () => setData(await api.detail(id))
  const canReview = data.status === 'awaiting_review' || data.status === 'analysis_failed'
  // With no AI verdict (failed analysis) the reviewer must name the cause, so the cause picker is always shown.
  const needsCause = !data.analysis || decision === 'rejected'

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setFormError(null); setMsg(null)
    try {
      localStorage.setItem('reviewer', reviewer)
      await api.review(id, { decision, reviewer, note: note.trim() || undefined, final_root_cause: needsCause ? cause : undefined })
      setMsg('Review saved. The product report is now marked stale.'); await refresh()
    } catch (err) { setFormError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) }
  }
  const reanalyze = async () => {
    setBusy(true); setFormError(null)
    try { await api.reanalyze(id); setMsg('Analysis started…'); setData({ ...data, status: 'analyzing' }); setRunKey((k) => k + 1) }
    catch (err) { setFormError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) }
  }

  return (
    <div>
      <button className="secondary" onClick={onBack}>← Queue</button>
      <div className="card">
        <div className="row between">
          <h2>Return <code>{data.id}</code> <StatusBadge status={data.status} /></h2>
          {data.status !== 'reviewed' && data.status !== 'analyzing' && data.status !== 'pending_analysis' && <button className="secondary" disabled={busy} onClick={reanalyze}>Reanalyze</button>}
        </div>
        <p><strong>{data.product_name}</strong> · {Object.entries(data.variant).map(([k, v]) => `${k}: ${v}`).join(', ')} · batch {data.batch_id ?? '—'} · order <code>{data.order_id}</code></p>
        <p>Customer said <strong>{label(data.stated_reason)}</strong>{data.comment ? <> — “{data.comment}”</> : <span className="muted"> (no comment)</span>}</p>
        <h4>Customer's media</h4>
        <MediaGallery media={data.media} />
        <h4>Seller's listing photos</h4>
        <ListingGallery images={data.listing_images} />
      </div>

      <div className="card">
        <h3>AI verdict</h3>
        {(data.status === 'analyzing' || (data.status === 'pending_analysis' && runKey > 0)) &&
          <div className="spinner-row"><span className="spinner" /> Analysis in progress… usually 10–30 s</div>}
        {data.status === 'pending_analysis' && runKey === 0 && (
          <div className="warn">
            This return has not been analyzed yet.
            <div><button disabled={busy} onClick={reanalyze}>{busy ? 'Starting…' : 'Run AI analysis'}</button></div>
          </div>
        )}
        {data.status === 'analysis_failed' && <div className="error">AI analysis failed. Decide manually below, or press Reanalyze.</div>}
        {data.analysis && <VerdictView analysis={data.analysis} findings={data.media_findings} media={data.media} statedReason={data.stated_reason} />}
      </div>

      <div className="card">
        <h3>Human decision</h3>
        {data.review ? (
          <div className={`decision ${data.review.decision}`}>
            <strong>{data.review.decision.toUpperCase()}</strong> by {data.review.reviewer} · final cause <strong>{label(data.review.final_root_cause)}</strong>
            {data.review.note && <p>“{data.review.note}”</p>}<small>{when(data.review.reviewed_at)}</small>
          </div>
        ) : canReview ? (
          <form onSubmit={submit}>
            <div className="radios">
              <label><input type="radio" checked={decision === 'accepted'} onChange={() => setDecision('accepted')} /> Accept the AI verdict</label>
              <label><input type="radio" checked={decision === 'rejected'} onChange={() => setDecision('rejected')} /> Reject it</label>
            </div>
            {needsCause && (
              <label>Final root cause{data.analysis && <span className="muted"> (must differ from the AI’s “{label(data.analysis.root_cause)}”)</span>}
                <select value={cause} onChange={(e) => setCause(e.target.value as Cause)}>
                  {CAUSES.filter((c) => c !== data.analysis?.root_cause).map((c) => <option key={c} value={c}>{label(c)}</option>)}
                </select>
              </label>
            )}
            <label>Note (optional)<textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} /></label>
            <label>Your name<input value={reviewer} onChange={(e) => setReviewer(e.target.value)} required maxLength={100} placeholder="e.g. anita" /></label>
            <ErrorBox error={formError} />
            <button type="submit" disabled={busy || !reviewer.trim()}>{busy ? 'Saving…' : 'Save decision'}</button>
          </form>
        ) : <p className="muted">This return can be reviewed once the analysis finishes.</p>}
        {msg && <div className="ok">{msg}</div>}
        {!canReview && <ErrorBox error={formError} />}
      </div>
    </div>
  )
}

export function ReviewerPage({ openId, setOpenId }: { openId: string | null; setOpenId: (id: string | null) => void }) {
  return openId ? <ReviewScreen id={openId} onBack={() => setOpenId(null)} /> : <Queue onOpen={setOpenId} />
}
