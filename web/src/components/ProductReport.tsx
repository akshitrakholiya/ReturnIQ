import { useEffect, useState } from 'react'
import { AlertTriangle, Check, CheckCircle2, Copy, Info, Minus, RotateCw, TrendingDown, TrendingUp } from 'lucide-react'
import { api } from '../api'
import { usePolling } from '../usePolling'
import type { EvidencePack, ProductReport, ReportResponse, ReportRootCause, RunStatus } from '../types'
import { ErrorBox, ago, attrLabel, label, money, pct, when } from './common'
import { EvidenceList, RefChip } from './EvidenceView'

const STEPS: { key: RunStatus; name: string; what: string }[] = [
  { key: 'gathering', name: 'Gathering evidence', what: 'Counting returns by size, batch, warehouse and week; reading comments and listing changes' },
  { key: 'finding_causes', name: 'Finding the root cause', what: 'The AI compares the patterns and checks each idea against the data' },
  { key: 'preparing_fixes', name: 'Preparing fixes', what: 'Writing a specific fix for each problem and checking every number' },
]
const OWNER = {
  seller: { text: 'You (the seller)', hint: 'product or listing' },
  logistics: { text: 'Logistics', hint: 'warehouse or courier' },
  none: { text: 'Nobody', hint: 'customer preference' },
}
const SCORE_PARTS: Record<string, string> = {
  share: 'Share of returns', volume: 'Number of returns', agreement: 'Different sources agree',
  photo: 'Photos support it', contradiction: 'Evidence against it',
}

function Progress({ status, startedAt }: { status: RunStatus; startedAt: string | null }) {
  const at = STEPS.findIndex((s) => s.key === status)
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(t) }, [])
  const secs = startedAt ? Math.max(0, Math.round((Date.now() - new Date(startedAt).getTime()) / 1000)) : 0
  return (
    <ol className="stepper">
      {STEPS.map((s, i) => {
        const state = status === 'done' || i < at ? 'done' : i === at ? 'now' : 'todo'
        return (
          <li key={s.key} className={state}>
            <span className="step-dot">{state === 'done' ? <Check size={14} strokeWidth={3} /> : state === 'now' ? <span className="spinner sm" /> : i + 1}</span>
            <div><strong>{s.name}</strong>{state === 'now' && <small> · {secs}s</small>}<p>{s.what}</p></div>
          </li>
        )
      })}
    </ol>
  )
}

/** Polls one run until it is done or failed (the HLD: every 2-3 s, no websockets). */
function RunWatcher({ productId, runId, onFinished }: { productId: string; runId: string; onFinished: (r: ReportResponse) => void }) {
  const { data, error } = usePolling(() => api.reportRun(productId, runId),
    (d) => d.run?.status === 'done' || d.run?.status === 'failed', 2500, [productId, runId])
  useEffect(() => { if (data?.run && (data.run.status === 'done' || data.run.status === 'failed')) onFinished(data) },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data?.run?.status])
  return (
    <div className="card">
      <h3>Analyzing this product…</h3>
      <p className="muted">This usually takes under a minute. You can keep browsing; the analysis continues in the background.</p>
      <Progress status={data?.run?.status ?? 'gathering'} startedAt={data?.run?.started_at ?? null} />
      <ErrorBox error={error} />
    </div>
  )
}

function Verdict({ r }: { r: ProductReport }) {
  const n = r.root_causes.length
  const [tone, title] = r.status === 'healthy' ? ['good', 'Looks healthy']
    : r.status === 'not_enough_data' ? ['neutral', 'Not enough returns yet']
    : n ? ['bad', `${n} problem${n > 1 ? 's' : ''} found`] : ['neutral', 'No clear problem found']
  return (
    <div className={`verdict-banner ${tone}`}>
      {tone === 'good' ? <CheckCircle2 size={20} /> : tone === 'bad' ? <AlertTriangle size={20} /> : <Info size={20} />}
      <div><strong>{title}</strong><p>{r.summary}</p></div>
    </div>
  )
}

function Stats({ r }: { r: ProductReport }) {
  const m = r.metrics
  const x = m.category_rate ? m.return_rate / m.category_rate : 0
  return (
    <div className="stats">
      <div className={`stat ${x > 1.2 ? 'bad' : ''}`}><small>Return rate</small><strong>{pct(m.return_rate)}</strong>
        <small>{m.returns} of {m.orders} orders</small></div>
      <div className="stat"><small>Category average</small><strong>{pct(m.category_rate)}</strong>
        <small>{x ? (x >= 1.05 ? `${x.toFixed(1)}× the average` : x <= 0.95 ? 'below average' : 'about average') : '—'}</small></div>
      <div className={`stat trend-${m.trend}`}><small>Trend</small>
        <strong className="with-icon">{m.trend === 'rising' ? <><TrendingUp size={18} />Rising</> : m.trend === 'falling' ? <><TrendingDown size={18} />Falling</> : <><Minus size={18} />Steady</>}</strong>
        <small>{m.previous_return_rate === null ? 'no earlier data' : `was ${pct(m.previous_return_rate)} before`}</small></div>
      {r.reason_mismatch_share !== null && <div className="stat"><small>Wrong reason picked</small>
        <strong>{pct(r.reason_mismatch_share)}</strong><small>by the customer</small></div>}
    </div>
  )
}

function ProblemCard({ c, onRef }: { c: ReportRootCause; onRef: (id: string) => void }) {
  const a = c.affected
  const chips = [...a.sizes.map((s) => `Size ${s}`), ...a.colors.map((s) => `Color ${s}`), ...a.batches.map((s) => `Batch ${s}`),
    ...a.warehouses.map((s) => `${s} warehouse`), ...a.attributes.map(attrLabel)]
  const [copied, setCopied] = useState(false)
  const copy = () => { if (c.fix) navigator.clipboard?.writeText(c.fix).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) }) }
  const owner = OWNER[c.owner]
  return (
    <div className="card problem">
      <div className="problem-head">
        <span className="rank">Problem {c.rank}</span>
        <h3>{c.title}</h3>
        <span className="badge">{label(c.cause)}</span>
      </div>
      {chips.length > 0 && <div className="row wrap"><small>Affects</small>{chips.map((x) => <span key={x} className="chip">{x}</span>)}</div>}

      {c.fix ? (
        <div className="fix">
          <div className="row between"><small>What to do</small>
            <button type="button" className="link with-icon" onClick={copy}>{copied ? <><Check size={14} />Copied</> : <><Copy size={14} />Copy</>}</button></div>
          <p>{c.fix}</p>
        </div>
      ) : c.owner === 'none'
        ? <div className="note">No fix needed from you: this comes from customer preference.</div>
        : <div className="warn">The suggested fix could not be verified against the data, so it is not shown.</div>}

      <div className="facts">
        <div><small>Who can fix it</small><strong>{owner.text}</strong><small>{owner.hint}</small></div>
        <div><small>How sure we are</small>
          <div className={`meter ${c.confidence.level}`}><div style={{ width: `${c.confidence.score}%` }} /></div>
          <strong className="cap">{c.confidence.level}</strong><small>{c.confidence.score} out of 100</small></div>
        <div><small>What it costs you</small><strong>{money(c.impact.monthly_cost_inr)} / month</strong>
          <small>≈ {c.impact.extra_returns_per_month} extra returns × {money(c.impact.cost_per_return_inr)}</small></div>
      </div>

      <h4>Why we think so</h4>
      <EvidenceList items={c.evidence} onOpen={onRef} />
      {c.counter_evidence.length > 0 && <><h4>What doesn't fit</h4><EvidenceList items={c.counter_evidence} onOpen={onRef} counter /></>}
      <details><summary>How “{c.confidence.level}” was worked out</summary>
        <table className="compact"><tbody>{Object.entries(c.confidence.breakdown).map(([k, v]) => (
          <tr key={k}><td>{SCORE_PARTS[k] ?? k}</td><td className={v < 0 ? 'up' : ''}>{v > 0 ? `+${v}` : v}</td></tr>))}
          <tr><td><strong>Total</strong></td><td><strong>{c.confidence.score}</strong></td></tr></tbody></table>
        <small className="muted">High is 75 or more, medium 50–74. Calculated from the data, not by the AI.</small>
      </details>
    </div>
  )
}

export function ReportView({ productId, onRef, onPack, onReady }: {
  productId: string; onRef: (id: string) => void; onPack: (p: EvidencePack | null) => void
  onReady: (hasReport: boolean) => void
}) {
  const [resp, setResp] = useState<ReportResponse | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const take = (r: ReportResponse) => {
    setResp(r)
    const s = r.run?.status
    setRunId(r.run && s !== 'done' && s !== 'failed' ? r.run.run_id : null)
    setFailed(s === 'failed' ? r.run!.error ?? 'analysis failed' : null)
  }
  useEffect(() => {
    setResp(null); setRunId(null); setFailed(null); setError(null)
    api.report(productId).then(take).catch((e) => setError(String(e)))
  }, [productId])

  const report = resp?.report ?? null
  useEffect(() => { onReady(report !== null) }, [report, onReady])
  useEffect(() => {
    onPack(null)
    if (report?.evidence_pack_id) api.evidencePack(productId, report.evidence_pack_id).then(onPack).catch(() => onPack(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productId, report?.evidence_pack_id])

  const refresh = async () => {
    setError(null)
    try { take(await api.refreshReport(productId)) } catch (e) { setError(String(e)) }
  }

  if (runId) return <RunWatcher productId={productId} runId={runId} onFinished={take} />
  if (!resp) return <div className="card"><div className="spinner-row"><span className="spinner" /> Loading…</div><ErrorBox error={error} /></div>
  if (!report) return (
    <div className="card">
      <div className="error"><strong>The analysis did not finish.</strong> {failed && <><br /><small>{failed}</small></>}</div>
      <p className="muted">This is usually a temporary AI quota or timeout problem. The numbers in the product list are still correct.</p>
      <button onClick={refresh}>Try again</button><ErrorBox error={error} />
    </div>
  )

  const checks = report.checks
  const removed = checks.dropped_evidence.length + checks.number_mismatches.length + checks.dropped_causes.length
  return (
    <>
      <div className="card">
        <Verdict r={report} />
        <Stats r={report} />
        {report.top_reasons.length > 0 && <>
          <h4>Why customers return it</h4>
          <table className="bars"><tbody>{report.top_reasons.map((t) => (
            <tr key={t.cause}><td>{label(t.cause)}</td>
              <td><div className="hbar"><div style={{ width: `${t.share * 100}%` }} /><span>{t.count} · {pct(t.share)}</span></div></td></tr>))}
          </tbody></table>
        </>}
        <div className="row between meta">
          <small className="muted">Checked {resp.built_at ? ago(resp.built_at) : '—'} · last 90 days
            {report.model_version ? <> · written by AI ({report.model_version})</> : <> · no AI needed</>}</small>
          <button className="secondary with-icon" onClick={refresh}><RotateCw size={14} />Re-run analysis</button>
        </div>
        <ErrorBox error={error} />
      </div>

      {report.root_causes.map((c) => <ProblemCard key={c.cause_id} c={c} onRef={onRef} />)}

      {report.rejected_hypotheses.length > 0 && (
        <div className="card">
          <h3>Also checked, and ruled out</h3>
          <ul className="ruled">{report.rejected_hypotheses.map((h, i) => (
            <li key={i}><strong>{h.hypothesis}</strong><p>{h.reason}</p>
              <div className="row wrap">{h.refs.map((r) => <RefChip key={r} id={r} onOpen={onRef} />)}</div></li>))}
          </ul>
        </div>
      )}

      {(report.data_notes.length > 0 || removed > 0 || checks.retried_agent) && (
        <details className="card">
          <summary>Good to know about this analysis {report.data_notes.length > 0 && <span className="badge">{report.data_notes.length}</span>}</summary>
          {report.data_notes.length > 0 && <ul className="notes">{report.data_notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
          {(removed > 0 || checks.retried_agent) && <>
            <h4>Automatic quality checks</h4>
            <p className="muted">Every claim and number from the AI is checked against the data. Anything that did not match was removed:</p>
            <ul className="notes">
              {checks.retried_agent && <li>The AI was asked to correct its answer once.</li>}
              {checks.dropped_causes.map((x) => <li key={x}>Problem dropped: {x}</li>)}
              {checks.dropped_evidence.length > 0 && <li>Unknown sources removed: {checks.dropped_evidence.join(', ')}</li>}
              {checks.number_mismatches.length > 0 && <li>Unverified numbers removed: {checks.number_mismatches.join('; ')}</li>}
            </ul></>}
          {resp.built_at && <small className="muted">Built {when(resp.built_at)}{report.evidence_pack_id && <> · evidence {report.evidence_pack_id}</>}</small>}
        </details>
      )}
    </>
  )
}
