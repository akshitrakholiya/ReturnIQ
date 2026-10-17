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
