import type { Analysis, Finding, Media } from '../types'
import { Confidence, label } from './common'

/** The AI verdict, evidence and per-media findings. Used by both the customer test view and the reviewer. */
export function VerdictView({ analysis, findings, media, statedReason }: {
  analysis: Analysis; findings: Finding[]; media: Media[]; statedReason: string
}) {
  const idx = (id: string) => media.findIndex((m) => m.id === id) + 1
  return (
    <div className="verdict">
      <div className="causes">
        <div><small>Customer said</small><strong>{label(statedReason)}</strong></div>
        <div className="arrow">{analysis.reason_mismatch ? '≠' : '='}</div>
        <div><small>AI says</small><strong>{label(analysis.root_cause)}</strong></div>
      </div>
      {analysis.reason_mismatch && <div className="warn">Reason mismatch: the stated reason differs from what the evidence shows.</div>}
      <div className="row"><small>Confidence</small><Confidence value={analysis.confidence} /></div>
      <div className="row"><small>Recommended</small><strong>{label(analysis.recommended_action)}</strong>
        {analysis.needs_manual_review && <span className="badge status-analysis_failed">manual review needed</span>}</div>
      <p className="explanation">{analysis.explanation}</p>

      <h4>Evidence</h4>
      <ul className="evidence">
        {analysis.evidence.map((e, i) => <li key={i}><code>{e.ref}</code> {e.finding}</li>)}
      </ul>

      <h4>Media findings</h4>
      {findings.length === 0 ? <p className="muted">No media was analyzed.</p> : (
        <table>
          <thead><tr><th>Media</th><th>Defect</th><th>Severity</th><th>Damage</th><th>Matches listing</th><th>Description</th></tr></thead>
          <tbody>
            {findings.map((f) => (
              <tr key={f.id}>
                <td>#{idx(f.media_id)} <code>{f.media_id}</code></td>
                <td>{f.defect_type ? label(f.defect_type) : '—'}</td>
                <td><span className={`sev sev-${f.severity}`}>{f.severity}</span></td>
                <td>{f.visible_damage ? 'yes' : 'no'}</td>
                <td>{f.matches_listing === null ? '?' : f.matches_listing ? 'yes' : 'no'}</td>
                <td>{f.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {analysis.context_notes.length > 0 && (<>
        <h4>Data gaps the AI was told about</h4>
        <ul className="notes">{analysis.context_notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
      </>)}
      <small className="muted">model: {analysis.model_version ?? 'unknown'}</small>
    </div>
  )
}
