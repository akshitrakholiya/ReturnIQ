import { useEffect, useState } from 'react'
import { API } from './api'
import { CustomerPage } from './components/CustomerPage'
import { ReviewerPage } from './components/ReviewerPage'

type Tab = 'customer' | 'reviewer'

export default function App() {
  const [tab, setTab] = useState<Tab>('customer')
  const [openId, setOpenId] = useState<string | null>(null)
  const [apiUp, setApiUp] = useState<boolean | null>(null)

  useEffect(() => {
    fetch(`${API}/health`).then((r) => setApiUp(r.ok)).catch(() => setApiUp(false))
  }, [])

  const openReviewer = (id: string) => { setOpenId(id); setTab('reviewer') }

  return (
    <div className="app">
      <header>
        <h1>ReturnIQ <small>Flow A test console</small></h1>
        <nav className="tabs">
          <button className={tab === 'customer' ? 'active' : ''} onClick={() => setTab('customer')}>Customer</button>
          <button className={tab === 'reviewer' ? 'active' : ''} onClick={() => { setTab('reviewer'); setOpenId(null) }}>Reviewer</button>
        </nav>
        <span className={`api ${apiUp === null ? '' : apiUp ? 'up' : 'down'}`}>API {apiUp === null ? '…' : apiUp ? 'connected' : 'not reachable'}</span>
      </header>
      {apiUp === false && <div className="error">Cannot reach the API at {API}. Start it with <code>uvicorn app.main:app --reload</code>.</div>}
      <main>
        {tab === 'customer' ? <CustomerPage onReview={openReviewer} /> : <ReviewerPage openId={openId} setOpenId={setOpenId} />}
      </main>
    </div>
  )
}
