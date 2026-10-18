import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, FileSearch, ImagePlus, ScrollText, Truck, UserCheck } from 'lucide-react'
import { api } from '../api'
import { usePolling } from '../usePolling'
import type { DemoOrder, DemoProduct } from '../types'
import { STATED_REASONS } from '../types'
import { ErrorBox, Folio, PageHead, StatusBadge, label, money, productName, when } from './common'
import { MediaGallery } from './MediaGallery'
import { Reticle, useScout } from './scout'
import { Select } from './Select'
import { VerdictView } from './VerdictView'

const DONE = ['awaiting_review', 'reviewed', 'analysis_failed']

// What the analysis looks at (README: tools = order_shipment, product_catalog, multimodal, policy).
const CHECKS = [
  { icon: FileSearch, title: 'Photos against the listing', text: 'Every photo is compared with what the seller advertised.' },
  { icon: Truck, title: 'Order, batch and shipment', text: 'Size, production batch, warehouse and delivery history.' },
  { icon: ScrollText, title: 'The return policy', text: 'The recommended action follows the written policy.' },
  { icon: UserCheck, title: 'A person decides', text: 'ReturnIQ recommends. A reviewer makes the final call.' },
]

function Progress({ returnId, onReview }: { returnId: string; onReview: (id: string) => void }) {
  const { data, error } = usePolling(() => api.detail(returnId), (d) => DONE.includes(d.status), 2500, [returnId])
  const working = !!data && !DONE.includes(data.status)
  useScout(working ? 'NOSE_TO_GROUND' : null, 'Cross-referencing the photos with the catalog specs.')
  if (!data) return <div className="card"><p>Submitting…</p><ErrorBox error={error} /></div>
  return (
    <>
      <PageHead index="02" module="FLOW A · GUARD" title="Return" em={data.id}
        lede={<>{productName(data.product_name)} · {Object.entries(data.variant).map(([k, v]) => `${k}: ${v}`).join(', ')} · batch {data.batch_id ?? '—'}</>}>
        <StatusBadge status={data.status} />
        {!working && <button onClick={() => onReview(data.id)}>Open in reviewer <ArrowRight size={14} /></button>}
      </PageHead>
      <div className="split">
        <section className="card">
          <Folio n="A">The claim</Folio>
          <p className="claim">Customer said <strong>{label(data.stated_reason)}</strong>{data.comment ? <> — <q>{data.comment}</q></> : null}</p>
          <Folio n="B">Evidence submitted</Folio>
          <MediaGallery media={data.media} />
        </section>
        <section className="card">
          <Folio n="C" aside="ReturnIQ">The finding</Folio>
          {working && (
            <div className="working">
              <Reticle state="NOSE_TO_GROUND" size={56} />
              <div><p className="working-title">ReturnIQ is <em>analyzing.</em></p>
                <p className="muted">{label(data.status)}… usually 15–30 s. You can leave this page open.</p></div>
            </div>
          )}
          {data.status === 'analysis_failed' && <div className="error">The AI could not analyze this return. A reviewer must decide manually (or press reanalyze in the reviewer).</div>}
          {data.analysis && <>
            <p className="note">Test view only: a real customer would not see the AI verdict.</p>
            <VerdictView analysis={data.analysis} findings={data.media_findings} media={data.media} statedReason={data.stated_reason} />
          </>}
          <ErrorBox error={error} />
        </section>
      </div>
    </>
  )
}

function Previews({ files }: { files: File[] }) {
  const urls = useMemo(() => files.map((f) => (f.type.startsWith('image/') ? URL.createObjectURL(f) : null)), [files])
  useEffect(() => () => urls.forEach((u) => u && URL.revokeObjectURL(u)), [urls])
  return (
    <div className="thumbs">{files.map((f, i) => (
      <figure key={f.name + f.size}>{urls[i] ? <img src={urls[i]!} alt={f.name} /> : <div className="media-fail">{f.name}</div>}
        <figcaption>{f.name}</figcaption></figure>
    ))}</div>
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
    <button className="link back with-icon" onClick={reset}><ArrowLeft size={14} />Start another return</button>
    <Progress returnId={submitted} onReview={onReview} />
  </>)

  return (
    <>
      <PageHead index="02" module="FLOW A · GUARD" title="Start a" em="return."
        lede="Test as a customer. Pick an order that has not been returned yet." />
      <div className="intake">
        <form className="card form" onSubmit={submit}>
          <div className="field">
            <label htmlFor="product"><span className="idx">01</span>Product</label>
            <Select id="product" value={productId} onChange={setProductId} placeholder="Choose a product…"
              options={products.map((p) => ({
                value: p.id, label: productName(p.name), text: `${productName(p.name)} ${label(p.category)}`, hint: label(p.category),
                meta: p.returnable_orders ? `${p.returnable_orders} returnable` : 'none left', disabled: !p.returnable_orders,
              }))} />
          </div>
          <div className="field">
            <label htmlFor="order"><span className="idx">02</span>Order</label>
            <Select id="order" value={orderId} onChange={setOrderId} disabled={!orders.length}
              placeholder={productId ? 'Loading orders…' : 'Pick a product first'}
              options={orders.map((o) => ({
                value: o.id, label: <span className="mono">{o.id}</span>, text: o.id,
                hint: <>{Object.entries(o.variant).map(([k, v]) => `${k} ${v}`).join(', ')} · batch {o.batch_id ?? '—'}{o.warehouse ? ` · ${o.warehouse}` : ''}</>,
                meta: <>{money(o.price)}<br />{when(o.order_date).split(',')[0]}</>,
              }))} />
          </div>
          <fieldset className="field">
            <legend><span className="idx">03</span>Reason</legend>
            <div className="choices">{STATED_REASONS.map((r) => (
              <label key={r} className={`choice ${reason === r ? 'on' : ''}`}>
                <input type="radio" name="reason" value={r} checked={reason === r} onChange={() => setReason(r)} />{label(r)}
              </label>))}
            </div>
          </fieldset>
          <div className="field">
            <label><span className="idx">04</span>Comment <small>(optional)</small>
              <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3} maxLength={1000}
                placeholder="e.g. The sole came off after two days" />
            </label>
          </div>
          <div className="field">
            <label className="dropzone"><span className="idx">05</span>Photos / video <small>(max 5)</small>
              <span className="drop"><ImagePlus size={20} strokeWidth={1.5} /><span><strong>Drop files here</strong> or click to browse</span>
                <small>{files.length ? `${files.length} selected` : 'JPEG, PNG, WebP, MP4, MOV'}</small></span>
              <input type="file" multiple accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime"
                onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 5))} />
            </label>
            {files.length > 0 && <Previews files={files} />}
          </div>
          <ErrorBox error={error} />
          <div className="form-foot">
            <button type="submit" disabled={busy || !orderId}>{busy ? 'Uploading and submitting…' : <>Submit return <ArrowRight size={14} /></>}</button>
          </div>
        </form>

        <aside className="card aside-card">
          <Folio n="i">What ReturnIQ checks</Folio>
          <ul className="checks">{CHECKS.map(({ icon: Icon, title, text }) => (
            <li key={title}><Icon size={16} strokeWidth={1.5} /><div><strong>{title}</strong><p>{text}</p></div></li>))}
          </ul>
        </aside>
      </div>
    </>
  )
}
