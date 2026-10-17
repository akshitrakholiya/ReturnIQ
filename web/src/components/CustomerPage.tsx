import { useEffect, useState } from 'react'
import { api } from '../api'
import { usePolling } from '../usePolling'
import type { DemoOrder, DemoProduct } from '../types'
import { STATED_REASONS } from '../types'
import { ErrorBox, StatusBadge, label, money, productName, when } from './common'
import { MediaGallery } from './MediaGallery'
import { VerdictView } from './VerdictView'

const DONE = ['awaiting_review', 'reviewed', 'analysis_failed']

function Progress({ returnId, onReview }: { returnId: string; onReview: (id: string) => void }) {
  const { data, error } = usePolling(() => api.detail(returnId), (d) => DONE.includes(d.status), 2500, [returnId])
  if (!data) return <div className="card"><p>Submitting…</p><ErrorBox error={error} /></div>
  const working = !DONE.includes(data.status)
  return (
    <div className="card">
      <div className="row between">
        <h3>Return <code>{data.id}</code> <StatusBadge status={data.status} /></h3>
        {!working && <button onClick={() => onReview(data.id)}>Open in reviewer →</button>}
      </div>
      <p className="muted">{productName(data.product_name)} · {Object.entries(data.variant).map(([k, v]) => `${k}: ${v}`).join(', ')} · batch {data.batch_id ?? '—'}</p>
      <p>Customer said <strong>{label(data.stated_reason)}</strong>{data.comment ? <> — “{data.comment}”</> : null}</p>
      <MediaGallery media={data.media} />
      {working && <div className="spinner-row"><span className="spinner" /> The AI is analyzing this return ({label(data.status)})… usually 15–30 s</div>}
      {data.status === 'analysis_failed' && <div className="error">The AI could not analyze this return. A reviewer must decide manually (or press reanalyze in the reviewer).</div>}
      {data.analysis && <>
        <p className="muted">Test view only: a real customer would not see the AI verdict.</p>
        <VerdictView analysis={data.analysis} findings={data.media_findings} media={data.media} statedReason={data.stated_reason} />
      </>}
      <ErrorBox error={error} />
    </div>
  )
}

export function CustomerPage({ onReview }: { onReview: (id: string) => void }) {
  const [products, setProducts] = useState<DemoProduct[]>([])
  const [orders, setOrders] = useState<DemoOrder[]>([])
  const [productId, setProductId] = useState('')
  const [orderId, setOrderId] = useState('')
  const [reason, setReason] = useState<string>('size_fit')
  const [comment, setComment] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState<string | null>(null)

  useEffect(() => { api.products().then(setProducts).catch((e) => setError(String(e))) }, [])
  useEffect(() => {
    setOrders([]); setOrderId('')
    if (productId) api.orders(productId).then((o) => { setOrders(o); setOrderId(o[0]?.id ?? '') }).catch((e) => setError(String(e)))
  }, [productId])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const media = []
      for (const f of files) media.push({ storage_url: await api.uploadMedia(f) })
      const r = await api.createReturn({ order_id: orderId, stated_reason: reason, comment: comment.trim() || null, media })
      setSubmitted(r.return_id)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) }
  }

  const reset = () => { setSubmitted(null); setFiles([]); setComment(''); setProductId('') ; api.products().then(setProducts) }

  if (submitted) return (<>
    <Progress returnId={submitted} onReview={onReview} />
    <button className="secondary" onClick={reset}>← Start another return</button>
  </>)

  return (
    <form className="card" onSubmit={submit}>
      <h2>Start a return</h2>
      <p className="muted">Test as a customer. Pick an order that has not been returned yet.</p>
      <label>Product
        <select value={productId} onChange={(e) => setProductId(e.target.value)} required>
          <option value="">Choose a product…</option>
          {products.map((p) => <option key={p.id} value={p.id} disabled={!p.returnable_orders}>{productName(p.name)} ({label(p.category)}) — {p.returnable_orders} returnable orders</option>)}
        </select>
      </label>
      <label>Order
        <select value={orderId} onChange={(e) => setOrderId(e.target.value)} required disabled={!orders.length}>
          {orders.map((o) => (
            <option key={o.id} value={o.id}>
              {o.id} · {Object.entries(o.variant).map(([k, v]) => `${k} ${v}`).join(', ')} · batch {o.batch_id ?? '—'} · {money(o.price)} · {when(o.order_date).split(',')[0]}{o.warehouse ? ` · ${o.warehouse}` : ''}
            </option>
          ))}
        </select>
      </label>
      <label>Reason
        <select value={reason} onChange={(e) => setReason(e.target.value)}>
          {STATED_REASONS.map((r) => <option key={r} value={r}>{label(r)}</option>)}
        </select>
      </label>
      <label>Comment (optional)
        <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3} maxLength={1000}
          placeholder="e.g. The sole came off after two days" />
      </label>
      <label>Photos / video (max 5)
        <input type="file" multiple accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime"
          onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 5))} />
      </label>
      {files.length > 0 && (
        <div className="thumbs">{files.map((f) => (
          <div key={f.name + f.size}>{f.type.startsWith('image/') ? <img src={URL.createObjectURL(f)} alt={f.name} /> : <div className="media-fail">{f.name}</div>}</div>
        ))}</div>
      )}
      <ErrorBox error={error} />
      <button type="submit" disabled={busy || !orderId}>{busy ? 'Uploading and submitting…' : 'Submit return'}</button>
    </form>
  )
}
