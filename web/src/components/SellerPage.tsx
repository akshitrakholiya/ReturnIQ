import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ChevronRight, RefreshCw, Search, Store } from 'lucide-react'
import { api } from '../api'
import type { EvidencePack, Seller, SellerProduct, ToolResult } from '../types'
import { ErrorBox, ago, label, pct, productName } from './common'
import { EvidencePanel } from './EvidenceView'
import { ReportView } from './ProductReport'
import { QAChat } from './QAChat'

type Filter = 'all' | 'attention' | 'problems' | 'unchecked'
const high = (p: SellerProduct) => p.category_rate !== null && p.return_rate > 1.2 * p.category_rate

function Analysis({ p }: { p: SellerProduct }) {
  if (p.run_status) return <span className="status info"><span className="spinner sm" />Analyzing</span>
  if (!p.report_status) return <span className="status">Not checked</span>
  if (p.report_status === 'healthy') return <span className="status good">Healthy</span>
  if (p.report_status === 'not_enough_data') return <span className="status">Too few returns</span>
  const n = p.root_causes ?? 0
  return <span className={`status ${n ? 'bad' : 'neutral'}`}>{n ? `${n} problem${n > 1 ? 's' : ''}` : 'No clear problem'}</span>
}

function RateBar({ p }: { p: SellerProduct }) {
  const scale = 0.5 // 50% return rate = full bar
  return (
    <div className="rate" title={p.category_rate !== null ? `Category average ${pct(p.category_rate)}` : ''}>
      <div className="rate-track">
        <div className={`rate-fill ${high(p) ? 'bad' : ''}`} style={{ width: `${Math.min(p.return_rate / scale, 1) * 100}%` }} />
        {p.category_rate !== null && <div className="rate-avg" style={{ left: `${Math.min(p.category_rate / scale, 1) * 100}%` }} />}
      </div>
      <span className={high(p) ? 'bad' : ''}>{pct(p.return_rate)}</span>
    </div>
  )
}

function ProductList({ sellerId, onOpen }: { sellerId: string; onOpen: (p: SellerProduct) => void }) {
  const [items, setItems] = useState<SellerProduct[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const [filter, setFilter] = useState<Filter>('all')
  const [q, setQ] = useState('')
  useEffect(() => { api.sellerProducts(sellerId).then((r) => { setItems(r); setError(null) }).catch((e) => setError(String(e))) }, [sellerId, tick])

  const all = useMemo(() => items ?? [], [items])
  const attention = all.filter(high)
  const problems = all.filter((p) => (p.root_causes ?? 0) > 0)
  const unchecked = all.filter((p) => !p.report_status)
  const returns = all.reduce((s, p) => s + p.returns, 0)
  const orders = all.reduce((s, p) => s + p.orders, 0)
  const shown = (filter === 'attention' ? attention : filter === 'problems' ? problems : filter === 'unchecked' ? unchecked : all)
    .filter((p) => !q || `${p.name} ${p.product_id} ${p.category}`.toLowerCase().includes(q.toLowerCase()))

  return (
    <>
      <div className="tiles">
        <button className={`tile ${filter === 'attention' ? 'on' : ''}`} onClick={() => setFilter('attention')}>
          <small>Need attention</small><strong className={attention.length ? 'bad' : ''}>{attention.length}</strong><small>return rate &gt; 1.2× category</small></button>
        <button className={`tile ${filter === 'problems' ? 'on' : ''}`} onClick={() => setFilter('problems')}>
          <small>Problems found</small><strong>{problems.length}</strong><small>by the AI analysis</small></button>
        <button className={`tile ${filter === 'unchecked' ? 'on' : ''}`} onClick={() => setFilter('unchecked')}>
          <small>Not checked yet</small><strong>{unchecked.length}</strong><small>open one to analyze it</small></button>
        <button className={`tile ${filter === 'all' ? 'on' : ''}`} onClick={() => setFilter('all')}>
          <small>All products</small><strong>{all.length}</strong><small>{returns} returns · {orders ? pct(returns / orders) : '—'} overall</small></button>
      </div>
      <div className="card">
        <div className="row between wrap">
          <h2>{{ all: 'All products', attention: 'Products that need attention', problems: 'Products with problems found', unchecked: 'Products not checked yet' }[filter]}</h2>
          <div className="row">
            <div className="search"><Search size={15} /><input placeholder="Search products" value={q} onChange={(e) => setQ(e.target.value)} /></div>
            <button className="icon-btn" onClick={() => setTick((t) => t + 1)} title="Reload" aria-label="Reload"><RefreshCw size={15} /></button>
          </div>
        </div>
        <p className="muted small">The marker on each bar is the category average.</p>
        <ErrorBox error={error} />
        <table className="clickable products">
          <thead><tr><th>Product</th><th>Orders</th><th>Returns</th><th>Return rate</th><th>Main reason</th><th>Analysis</th><th /></tr></thead>
          <tbody>
            {shown.map((p) => (
              <tr key={p.product_id} onClick={() => onOpen(p)}>
                <td><strong>{productName(p.name)}</strong><div><small>{label(p.category)} · {p.product_id}</small></div></td>
                <td>{p.orders}</td><td>{p.returns}</td>
                <td><RateBar p={p} /></td>
                <td>{p.top_cause ? label(p.top_cause) : <span className="muted">—</span>}</td>
                <td><Analysis p={p} />{p.report_built_at && <div><small>{ago(p.report_built_at)}{p.report_stale && ' · new reviews since'}</small></div>}</td>
                <td className="go"><ChevronRight size={16} /></td>
              </tr>
            ))}
            {items !== null && shown.length === 0 && <tr><td colSpan={7} className="muted empty">Nothing here{q && ' matches your search'}.</td></tr>}
            {items === null && !error && <tr><td colSpan={7}><div className="spinner-row"><span className="spinner" /> Loading…</div></td></tr>}
          </tbody>
        </table>
      </div>
    </>
  )
}

function ProductDetail({ product, onBack, onOpenReturn }: { product: SellerProduct; onBack: () => void; onOpenReturn: (id: string) => void }) {
  const [pack, setPack] = useState<EvidencePack | null>(null)
  const [panel, setPanel] = useState<{ id: string; tools?: ToolResult[] } | null>(null)
  const [ready, setReady] = useState(false)
  const onReady = useCallback((v: boolean) => setReady(v), [])
  return (
    <div>
      <button className="link back with-icon" onClick={onBack}><ArrowLeft size={15} />All products</button>
      <div className="product-head">
        <h2>{productName(product.name)}</h2>
        <small>{label(product.category)} · {product.product_id}</small>
      </div>
      <div className="detail">
        <div className="detail-main">
          <ReportView productId={product.product_id} onRef={(id) => setPanel({ id })} onPack={setPack} onReady={onReady} />
        </div>
        <div className="detail-side">
          <QAChat productId={product.product_id} ready={ready}
            onRef={(id, tools) => setPanel({ id, tools })} onOpenReturn={onOpenReturn} />
        </div>
      </div>
      {panel && <EvidencePanel id={panel.id} pack={pack} tools={panel.tools} onClose={() => setPanel(null)} onOpenReturn={onOpenReturn} />}
    </div>
  )
}

/** Flow B: the seller's view. A seller switcher stands in for login (Phase 1 demo). */
export function SellerPage({ onOpenReturn }: { onOpenReturn: (id: string) => void }) {
  const [sellers, setSellers] = useState<Seller[]>([])
  const [sellerId, setSellerId] = useState<string | null>(() => localStorage.getItem('seller'))
  const [product, setProduct] = useState<SellerProduct | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.sellers().then((s) => {
      setSellers(s)
      setSellerId((cur) => (cur && s.some((x) => x.id === cur) ? cur : s[0]?.id ?? null))
    }).catch((e) => setError(String(e)))
  }, [])
  const pick = (id: string) => { localStorage.setItem('seller', id); setSellerId(id); setProduct(null) }

  return (
    <div>
      <div className="row between wrap page-head">
        <div><h1>Product insights</h1>
          <p className="muted">Why your products come back, and what to change. Based on the last 90 days of returns.</p></div>
        {sellers.length > 1 ? (
          <label className="inline-label">Signed in as
            <select className="inline" value={sellerId ?? ''} onChange={(e) => pick(e.target.value)}>
              {sellers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select></label>
        ) : sellers[0] && <span className="who"><Store size={14} />{sellers[0].name}</span>}
      </div>
      <ErrorBox error={error} />
      {sellerId && (product
        ? <ProductDetail product={product} onBack={() => setProduct(null)} onOpenReturn={onOpenReturn} />
        : <ProductList sellerId={sellerId} onOpen={setProduct} />)}
    </div>
  )
}
