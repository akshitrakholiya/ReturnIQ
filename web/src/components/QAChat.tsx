import { useEffect, useRef, useState } from 'react'
import { ArrowUp, MessageSquareText } from 'lucide-react'
import { api } from '../api'
import type { CheckReport, QAAnswer, ToolResult } from '../types'
import { ErrorBox } from './common'
import { useScout } from './scout'
import { EvidenceList } from './EvidenceView'

interface Turn { question: string; answer: QAAnswer | null; checks?: CheckReport }

const SUGGESTIONS = [
  'Which sizes have the most returns?',
  'Are returns coming from one warehouse?',
  'Did returns rise after the last listing change?',
  'Is one batch worse than the others?',
]
const key = (productId: string) => `qa-session:${productId}`

/** Seller questions about one product. One conversation per product, kept across reloads. */
export function QAChat({ productId, ready, onRef, onOpenReturn }: {
  productId: string; ready: boolean
  onRef: (id: string, tools: ToolResult[]) => void; onOpenReturn: (id: string) => void
}) {
  const [sessionId, setSessionId] = useState<string | null>(() => localStorage.getItem(key(productId)))
  const [turns, setTurns] = useState<Turn[]>([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const sid = localStorage.getItem(key(productId))
    setSessionId(sid); setTurns([]); setError(null)
    if (sid) api.questions(productId, sid).then((h) => setTurns(h.map((t) => ({ question: t.question, answer: t.answer }))))
      .catch(() => setTurns([]))
  }, [productId])
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }) }, [turns.length, busy])
  useScout(busy ? 'NOSE_TO_GROUND' : null, 'Reading your return data to answer the question.')

  const ask = async (question: string) => {
    question = question.trim()
    if (!question || busy) return
    setBusy(true); setError(null); setQ('')
    setTurns((t) => [...t, { question, answer: null }])
    try {
      const r = await api.ask(productId, question, sessionId)
      localStorage.setItem(key(productId), r.session_id); setSessionId(r.session_id)
      setTurns((t) => [...t.slice(0, -1), { question, answer: r.answer, checks: r.checks }])
    } catch (e) {
      setTurns((t) => t.slice(0, -1)); setQ(question); setError(e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }
  const reset = () => { localStorage.removeItem(key(productId)); setSessionId(null); setTurns([]); setError(null) }

  return (
    <div className="card chat">
      <div className="mono-label eyebrow"><span>04</span> / CONSOLE</div>
      <div className="row between">
        <h3 className="with-icon"><MessageSquareText size={16} />Ask <em>Scout</em> about this product</h3>
        {turns.length > 0 && <button className="link" onClick={reset}>New chat</button>}
      </div>
      {!ready ? <p className="muted">You can ask questions once the analysis is ready.</p>
        : turns.length === 0 && <p className="muted">Ask anything about this product's returns. Answers come from your data, with sources.</p>}
      <div className="turns">
        {turns.map((t, i) => (
          <div key={i}>
            <div className="bubble q">{t.question}</div>
            {t.answer ? (
              <div className="bubble a">
                <p>{t.answer.answer}</p>
                {!t.answer.enough_data && <span className="badge status-awaiting_review">not enough data</span>}
                {t.answer.evidence.length > 0 && <><small className="muted">Sources</small>
                  <EvidenceList items={t.answer.evidence} onOpen={(id) => onRef(id, t.answer!.tool_results)} /></>}
                {t.answer.related_return_ids.length > 0 && (
                  <div className="row wrap"><small>Example returns</small>
                    {t.answer.related_return_ids.map((r) => <button key={r} type="button" className="chip ref" onClick={() => onOpenReturn(r)}>{r}</button>)}</div>)}
                {t.answer.tool_results.length > 0 && (
                  <details><summary><small>The AI looked up {t.answer.tool_results.length} extra thing{t.answer.tool_results.length > 1 ? 's' : ''}</small></summary>
                    <ul className="notes">{t.answer.tool_results.map((tr) => (
                      <li key={tr.ref_id}><code>{tr.ref_id}</code> {tr.tool}({Object.entries(tr.args).filter(([k]) => k !== 'product_id').map(([k, v]) => `${k}=${String(v)}`).join(', ')})</li>))}
                    </ul></details>)}
                {t.checks && t.checks.dropped_evidence.length + t.checks.number_mismatches.length > 0 && (
                  <small className="muted">Checks removed {[...t.checks.dropped_evidence, ...t.checks.number_mismatches].join(', ')}</small>)}
              </div>
            ) : <div className="bubble a typing"><span className="spinner sm" /> Looking at your data… usually under 15 s</div>}
          </div>
        ))}
        <div ref={end} />
      </div>
      {turns.length === 0 && ready && (
        <div className="suggestions"><small>Try asking</small>{SUGGESTIONS.map((s) => <button key={s} type="button" className="chip" onClick={() => ask(s)}>{s}</button>)}</div>
      )}
      <ErrorBox error={error} />
      <form className="ask" onSubmit={(e) => { e.preventDefault(); ask(q) }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type a question…"
          maxLength={500} disabled={!ready || busy} />
        <button type="submit" className="send" disabled={!ready || busy || q.trim().length < 2} aria-label="Ask"><ArrowUp size={16} /></button>
      </form>
    </div>
  )
}
