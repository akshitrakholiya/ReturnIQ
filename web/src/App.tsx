import { useEffect, useState } from 'react'
import { BarChart3, ClipboardCheck, PackageOpen, type LucideIcon } from 'lucide-react'
import { API } from './api'
import { CustomerPage } from './components/CustomerPage'
import { ReviewerPage } from './components/ReviewerPage'
import { SellerPage } from './components/SellerPage'

type Tab = 'customer' | 'reviewer' | 'seller'
const NAV: { group: string; key: Tab; name: string; icon: LucideIcon }[] = [
  { group: 'Customer', key: 'customer', name: 'Start a return', icon: PackageOpen },
  { group: 'Operations', key: 'reviewer', name: 'Review queue', icon: ClipboardCheck },
  { group: 'Seller', key: 'seller', name: 'Product insights', icon: BarChart3 },
]

export default function App() {
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem('tab') as Tab) || 'customer')
  const [openId, setOpenId] = useState<string | null>(null)
  const [apiUp, setApiUp] = useState<boolean | null>(null)

  useEffect(() => {
    fetch(`${API}/health`).then((r) => setApiUp(r.ok)).catch(() => setApiUp(false))
  }, [])

  const go = (t: Tab) => { setTab(t); localStorage.setItem('tab', t); if (t === 'reviewer') setOpenId(null) }
  const openReviewer = (id: string) => { setOpenId(id); setTab('reviewer') }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <svg className="logo" viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="6" /><path d="M7 15.5V8.5h5a3 3 0 0 1 0 6H9.5M12 14.5l3.5 3" /></svg>
          <span>ReturnIQ</span>
        </div>
        <nav>
          {NAV.map(({ group, key, name, icon: Icon }) => (
            <div key={key} className="nav-group">
              <small>{group}</small>
              <button className={tab === key ? 'active' : ''} onClick={() => go(key)}><Icon size={16} strokeWidth={2} />{name}</button>
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
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
  )
}
