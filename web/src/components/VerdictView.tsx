import { useState } from 'react'
import type { Analysis, Finding, Media } from '../types'
import { Confidence, label } from './common'
import { StateTag, useScout } from './scout'

function FindingThumb({ m }: { m?: Media }) {
  const [failed, setFailed] = useState(false)
  if (!m || failed || m.type === 'video') return <div className="finding-thumb empty">{m?.type === 'video' ? 'video' : 'no preview'}</div>
  return <a className="finding-thumb" href={m.view_url} target="_blank" rel="noreferrer"><img src={m.view_url} alt="" onError={() => setFailed(true)} /></a>
}

/** The AI verdict, evidence and per-media findings. Used by both the customer test view and the reviewer. */
export function VerdictView({ analysis, findings, media, statedReason }: {
  analysis: Analysis; findings: Finding[]; media: Media[]; statedReason: string
}) {
  const idx = (id: string) => media.findIndex((m) => m.id === id) + 1
  const mismatch = analysis.reason_mismatch
  useScout(mismatch ? 'HEAD_TILT_ALERT' : 'PROUD_CHECKMARK',
    mismatch ? `Customer stated “${label(statedReason)}”; the evidence says “${label(analysis.root_cause)}”.`
      : `The evidence corroborates “${label(statedReason)}”.`)
  return (
    <div className={`verdict ${mismatch ? 'is-alert' : 'is-ok'}`}>
      <div className="claimline">
        <div><span className="mono-label">Customer stated</span><strong>{label(statedReason)}</strong></div>
        <div className="relation" aria-label={mismatch ? 'does not match' : 'matches'}>{mismatch ? '≠' : '='}</div>
        <div><span className="mono-label">Scout found</span><strong>{label(analysis.root_cause)}</strong></div>
      </div>
      <div className="row wrap verdict-meta">
        <StateTag ok={!mismatch}>{mismatch ? 'Reason mismatch' : 'Claim verified'}</StateTag>
        {analysis.needs_manual_review && <span className="badge status-analysis_failed">manual review needed</span>}
      </div>
      {mismatch && <p className="muted small">The stated reason differs from what the evidence shows.</p>}
      <dl className="readout">
        <div><dt className="mono-label">Confidence</dt><dd><Confidence value={analysis.confidence} /></dd></div>
        <div><dt className="mono-label">Recommended</dt><dd><strong>{label(analysis.recommended_action)}</strong></dd></div>
      </dl>
      <blockquote className="explanation">{analysis.explanation}</blockquote>

      <h4>Evidence</h4>
      <ol className="footnotes">
        {analysis.evidence.map((e, i) => <li key={i}><code>{e.ref}</code><span>{e.finding}</span></li>)}
      </ol>

      <h4>Media findings</h4>
      {findings.length === 0 ? <p className="muted">No media was analyzed.</p> : (
        <div className="finding-grid">
          {findings.map((f) => (
            <article key={f.id} className="fcard">
              <FindingThumb m={media.find((m) => m.id === f.media_id)} />
              <div className="finding-body">
                <div className="row between"><span className="mono-label">#{idx(f.media_id)} · {f.media_id}</span><span className={`sev sev-${f.severity}`}>{f.severity}</span></div>
                <strong>{f.defect_type ? label(f.defect_type) : 'No defect'}</strong>
                <p>{f.description}</p>
                <div className="tags">
                  <span className={`tag ${f.visible_damage ? 'bad' : ''}`}>damage: {f.visible_damage ? 'yes' : 'no'}</span>
                  <span className={`tag ${f.matches_listing === false ? 'bad' : ''}`}>matches listing: {f.matches_listing === null ? '?' : f.matches_listing ? 'yes' : 'no'}</span>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {analysis.context_notes.length > 0 && (<>
        <h4>Data gaps the AI was told about</h4>
        <ul className="notes">{analysis.context_notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
      </>)}
      <small className="muted mono">model: {analysis.model_version ?? 'unknown'}</small>
    </div>
  )
}
