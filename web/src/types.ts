export type Status = 'pending_analysis' | 'analyzing' | 'awaiting_review' | 'reviewed' | 'analysis_failed'

export const CAUSES = [
  'size_fit', 'defect_quality', 'damaged_in_transit', 'wrong_item',
  'not_as_described', 'changed_mind', 'suspicious', 'other',
] as const
export type Cause = (typeof CAUSES)[number]
// customers can pick anything except "suspicious"
export const STATED_REASONS = CAUSES.filter((c) => c !== 'suspicious')

export interface DemoProduct { id: string; name: string; category: string; returnable_orders: number }
export interface DemoOrder {
  id: string; variant: Record<string, string>; batch_id: string | null; price: number
  order_date: string; warehouse: string | null; delivered_date: string | null
}

export interface QueueItem {
  id: string; status: Status; stated_reason: Cause; created_at: string; product_name: string
  ai_root_cause: Cause | null; confidence: number | null; needs_manual_review: boolean | null; media_count: number
}

export interface Media { id: string; type: 'photo' | 'video'; storage_url: string; mime_type: string; size_bytes: number; view_url: string }
export interface Analysis {
  id: string; root_cause: Cause; reason_mismatch: boolean; confidence: number; explanation: string
  evidence: { ref: string; finding: string }[]; context_notes: string[]
  recommended_action: string; needs_manual_review: boolean; model_version: string | null; created_at: string
}
export interface Finding {
  id: string; media_id: string; defect_type: string | null; severity: string
  visible_damage: boolean; matches_listing: boolean | null; description: string
}
export interface Review { decision: 'accepted' | 'rejected'; final_root_cause: Cause; note: string | null; reviewer: string; reviewed_at: string }

export interface ReturnDetail {
  id: string; status: Status; stated_reason: Cause; comment: string | null; created_at: string
  order_id: string; product_id: string; product_name: string; category: string
  variant: Record<string, string>; batch_id: string | null; price: number; order_date: string
  listing_images: { storage_url: string; view_url: string }[]
  media: Media[]; analysis: Analysis | null; media_findings: Finding[]; review: Review | null
}

// ───────────── Flow B (seller) — mirrors server/app/schemas/flow_b.py ─────────────
export type Owner = 'seller' | 'logistics' | 'none'
export type RunStatus = 'gathering' | 'finding_causes' | 'preparing_fixes' | 'done' | 'failed'

export interface Seller { id: string; name: string; products: number }
export interface SellerProduct {
  product_id: string; name: string; category: string; orders: number; returns: number; return_rate: number
  top_cause: Cause | null; category_rate: number | null; report_stale: boolean
  report_id: string | null; report_status: ProductReport['status'] | null; report_built_at: string | null
  root_causes: number | null; run_status: RunStatus | null
}

export interface EvidenceRef { ref: string; finding: string }
export interface ProductMetrics {
  orders: number; returns: number; return_rate: number; previous_return_rate: number | null
  category_rate: number; trend: 'rising' | 'flat' | 'falling'
}
export interface ReasonShare { cause: Cause; count: number; share: number }
export interface Affected { sizes: string[]; colors: string[]; batches: string[]; warehouses: string[]; attributes: string[] }
export interface ReportRootCause {
  cause_id: string; title: string; cause: Cause; owner: Owner; evidence: EvidenceRef[]; counter_evidence: EvidenceRef[]
  affected: Affected; fix: string | null; rank: number
  confidence: { score: number; level: 'high' | 'medium' | 'low'; breakdown: Record<string, number> }
  impact: { extra_returns_per_month: number; cost_per_return_inr: number; monthly_cost_inr: number }
}
export interface CheckReport { dropped_evidence: string[]; number_mismatches: string[]; dropped_causes: string[]; retried_agent: boolean }
export interface ProductReport {
  product_id: string; evidence_pack_id: string | null; status: 'analyzed' | 'not_enough_data' | 'healthy'
  period: string; summary: string; metrics: ProductMetrics; root_causes: ReportRootCause[]
  rejected_hypotheses: { hypothesis: string; reason: string; refs: string[] }[]
  reason_mismatch_share: number | null; top_reasons: ReasonShare[]; data_notes: string[]
  checks: CheckReport; model_version: string | null
}
export interface ReportRun { run_id: string; product_id: string; status: RunStatus; error: string | null; started_at: string; finished_at: string | null }
export interface ReportResponse { product_id: string; report_id: string | null; run: ReportRun | null; report: ProductReport | null; built_at: string | null }

export interface BreakdownRow { group: string; count: number; share: number; previous_count: number | null; change: number | null }
export interface EvidencePack {
  pack_id: string; product_id: string; period: string; metrics: ProductMetrics
  breakdowns: { id: string; group_by: string; filter: Record<string, string>; rows: BreakdownRow[] }[]
  feedback: { return_id: string; cause: Cause | null; reviewed: boolean; stated_reason: string; comment: string | null
              reviewer_note: string | null; media_finding: string | null; variant: Record<string, string> }[]
  listing: { title: string; category: string; description: string; attributes: Record<string, unknown>; listing_image_urls: string[] }
  listing_changes: { id: string; field: string; old_value: unknown; new_value: unknown; changed_at: string }[]
  profile: { category: string; variant_dimensions: string[]; key_attributes: string[]; media_focus: string; listing_checks: string[] }
  completeness_notes: string[]; created_at: string
}

export interface ToolResult { ref_id: string; tool: string; args: Record<string, unknown>; data: Record<string, unknown> }
export interface QAAnswer { answer: string; evidence: EvidenceRef[]; related_return_ids: string[]; enough_data: boolean; tool_results: ToolResult[] }
export interface QAResponse { qa_id: string; product_id: string; session_id: string; question: string; answer: QAAnswer; checks: CheckReport; created_at: string }
export interface QATurn { qa_id: string; session_id: string; question: string; answer: QAAnswer; created_at: string }
