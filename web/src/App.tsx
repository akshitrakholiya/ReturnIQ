import { useEffect, useState } from 'react'
import { BarChart3, ClipboardCheck, PackageOpen, type LucideIcon } from 'lucide-react'
import { API } from './api'
import { AuraPointer } from './components/AuraPointer'
import { CustomerPage } from './components/CustomerPage'
import { ReviewerPage } from './components/ReviewerPage'
import { SellerPage } from './components/SellerPage'
import { Aperture, ScoutProvider } from './components/scout'
import { Mark } from './components/common'

type Tab = 'customer' | 'reviewer' | 'seller'
// Same three destinations as before; they are now grouped by the flow they belong to.
const NAV: { module: string; index: string; items: { key: Tab; name: string; role: string; icon: LucideIcon }[] }[] = [
  { index: '02', module: 'FLOW A · GUARD', items: [
    { key: 'customer', name: 'Start a return', role: 'Customer', icon: PackageOpen },
    { key: 'reviewer', name: 'Review queue', role: 'Operations', icon: ClipboardCheck },
  ] },
  { index: '03', module: 'FLOW B · HOUND', items: [
    { key: 'seller', name: 'Product insights', role: 'Seller', icon: BarChart3 },
  ] },
]

export default function App() {
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem('tab') as Tab) || 'customer')
  const [openId, setOpenId] = useState<string | null>(null)
  const [apiUp, setApiUp] = useState<boolean | null>(null)
  const [latency, setLatency] = useState<number | null>(null)

  useEffect(() => {
    const t0 = performance.now()
    fetch(`${API}/health`).then((r) => { setApiUp(r.ok); setLatency(Math.round(performance.now() - t0)) }).catch(() => setApiUp(false))
  }, [])

  const go = (t: Tab) => { setTab(t); localStorage.setItem('tab', t); if (t === 'reviewer') setOpenId(null) }
  const openReviewer = (id: string) => { setOpenId(id); setTab('reviewer') }

  return (
    <ScoutProvider>
      <div className="shell">
        <aside className="rail">
          <div className="brand">
            <Mark />
            <div>
              <span className="wordmark">Return<em>IQ</em></span>
            </div>
          </div>
          <Aperture latency={apiUp ? latency : null} />
          <nav aria-label="Modules">
            {NAV.map(({ index, module, items }) => (
              <div key={index} className="nav-group">
                <div className="mono-label"><span>{index}</span> / {module}</div>
                {items.map(({ key, name, role, icon: Icon }) => (
                  <button key={key} className={tab === key ? 'active' : ''} aria-current={tab === key ? 'page' : undefined} onClick={() => go(key)}>
                    <Icon size={15} strokeWidth={1.75} />
                    <span>{name}</span>
                    <small>{role}</small>
                  </button>
                ))}
              </div>
            ))}
          </nav>
          <div className="rail-foot">
            <span className={`dot ${apiUp === null ? '' : apiUp ? 'up' : 'down'}`} />
            {apiUp === null ? 'Connecting…' : apiUp ? 'API connected' : 'API offline'}
          </div>
        </aside>
        <main className="content">
          {apiUp === false && <div className="error">Cannot reach the server at {API}. Start it with <code>uvicorn app.main:app --reload</code>.</div>}
          {tab === 'customer' ? <CustomerPage onReview={openReviewer} />
            : tab === 'reviewer' ? <ReviewerPage openId={openId} setOpenId={setOpenId} />
            : <SellerPage onOpenReturn={openReviewer} />}
        </main>
      </div>
      <AuraPointer />
    </ScoutProvider>
  )
}
