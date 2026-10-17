"""
ReturnIQ - Flow B (product detail analysis + seller Q&A) step contracts.

Every step has a typed input and a typed output. The API validates each
output before passing it to the next step, so a missing or wrong field is
caught at the step that produced it.

Pipeline (product detail):
    1. Cache check          (code)   ReportRequest      -> CacheCheckResult
    2. Health check         (code)   HealthCheckInput   -> HealthCheckResult
    3. Evidence pack        (code)   EvidencePackInput  -> EvidencePack
    4. RCA Agent            (agent)  RCAInput           -> RCAFindings
    5. Solution Agent       (agent)  SolutionInput      -> SolutionOutput
    6. Checks and scoring   (code)   ScoringInput       -> ProductReport
    7. Save and show        (code)   ProductReport      -> ReportResponse

Seller question:
    Q&A Agent               (agent)  QAInput            -> QAAnswer
    Checks                  (code)   QAAnswer           -> QAResponse

Requires: pydantic >= 2
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------

Period = Literal["this_month", "last_month", "last_30d", "last_90d"]
CompareTo = Literal["previous", "last_month", "last_90d"]
Owner = Literal["seller", "logistics", "none"]


class RootCause(str, Enum):
    size_fit = "size_fit"
    defect_quality = "defect_quality"
    damaged_in_transit = "damaged_in_transit"
    wrong_item = "wrong_item"
    not_as_described = "not_as_described"
    changed_mind = "changed_mind"
    suspicious = "suspicious"
    other = "other"


class EvidenceRef(BaseModel):
    """A single claim backed by an ID from the evidence pack or a tool result."""
    ref: str = Field(..., description="e.g. 'breakdown:size', 'r_101', 'listing'")
    finding: str = Field(..., description="Short claim in plain words")


class ToolResult(BaseModel):
    """Result of one drill-down tool call made by an agent during a run."""
    ref_id: str = Field(..., description="ID the agent can cite, e.g. 'tool:3'")
    tool: str
    args: dict[str, Any]
    data: dict[str, Any]


# ---------------------------------------------------------------------------
# Step 1 - Cache check (code)
# ---------------------------------------------------------------------------

class ReportRequest(BaseModel):
    product_id: str
    seller_id: str
    force_refresh: bool = False


class CacheCheckResult(BaseModel):
    status: Literal["fresh", "stale", "missing"]
    report_id: Optional[str] = None            # set when status is fresh or stale
    new_reviewed_returns: int = 0              # since the saved report was built
    # fresh  -> return saved report, stop
    # stale/missing (or force_refresh) -> continue to step 2


# ---------------------------------------------------------------------------
# Step 2 - Health check (code)
# ---------------------------------------------------------------------------

class HealthCheckInput(BaseModel):
    product_id: str
    category: str
    period: Period = "last_90d"


class ProductMetrics(BaseModel):
    orders: int
    returns: int
    return_rate: float
    previous_return_rate: Optional[float] = None
    category_rate: float
    trend: Literal["rising", "flat", "falling"]


class ReasonShare(BaseModel):
    cause: RootCause
    count: int
    share: float


class HealthCheckResult(BaseModel):
    decision: Literal["analyze", "not_enough_data", "healthy"]
    metrics: ProductMetrics
    top_reasons: list[ReasonShare] = Field(default_factory=list, max_length=3)
    # not_enough_data / healthy -> build a short ProductReport, no agents


# ---------------------------------------------------------------------------
# Step 3 - Evidence pack (code)
# ---------------------------------------------------------------------------

class EvidencePackInput(BaseModel):
    product_id: str
    category: str
    period: Period = "last_90d"
    compare_to: CompareTo = "previous"


class BreakdownRow(BaseModel):
    group: str                                  # e.g. "L", "B36", "Pune", "size_fit"
    count: int
    share: float
    previous_count: Optional[int] = None
    change: Optional[int] = None


class Breakdown(BaseModel):
    id: str                                     # e.g. "breakdown:size"
    group_by: str                               # root_cause, size, color, week, warehouse, batch, reason_mismatch, media_finding
    filter: dict[str, Any] = Field(default_factory=dict)
    rows: list[BreakdownRow]


class FeedbackItem(BaseModel):
    return_id: str                              # citable ID
    cause: Optional[RootCause] = None           # final_root_cause if reviewed, else AI cause
    reviewed: bool
    stated_reason: str
    comment: Optional[str] = None
    reviewer_note: Optional[str] = None
    media_finding: Optional[str] = None         # short stored finding, e.g. "sole separation, high"
    variant: dict[str, str] = Field(default_factory=dict)


class ListingInfo(BaseModel):
    id: str = "listing"
    title: str
    category: str
    description: str
    attributes: dict[str, Any]                  # size chart / specs / dimensions
    listing_image_urls: list[str] = Field(default_factory=list)


class ListingChange(BaseModel):
    id: str                                     # e.g. "listing_change:42"
    field: str
    old_value: Any
    new_value: Any
    changed_at: datetime


class CategoryProfile(BaseModel):
    id: str = "profile"
    category: str
    variant_dimensions: list[str]
    key_attributes: list[str]
    media_focus: str
    listing_checks: list[str]


class EvidencePack(BaseModel):
    pack_id: str
    product_id: str
    period: Period
    compare_to: CompareTo
    metrics: ProductMetrics                     # id "metrics" (includes baseline)
    breakdowns: list[Breakdown]
    feedback: list[FeedbackItem]
    listing: ListingInfo
    listing_changes: list[ListingChange] = Field(default_factory=list)
    profile: CategoryProfile
    completeness_notes: list[str] = Field(default_factory=list)
    created_at: datetime


# ---------------------------------------------------------------------------
# Step 4 - RCA Agent (agent)
# ---------------------------------------------------------------------------

class RCAInput(BaseModel):
    evidence_pack: EvidencePack
    max_tool_calls: int = 6


class Affected(BaseModel):
    """What the fix must target. Empty lists mean 'not specific to this dimension'."""
    sizes: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    batches: list[str] = Field(default_factory=list)
    warehouses: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)   # e.g. ["size_chart.length"]


class RootCauseFinding(BaseModel):
    cause_id: str                               # e.g. "c1"
    title: str
    cause: RootCause
    owner: Owner
    supporting_returns: int
    share: float
    evidence: list[EvidenceRef] = Field(..., min_length=2)
    counter_evidence: list[EvidenceRef] = Field(default_factory=list)
    affected: Affected


class RejectedHypothesis(BaseModel):
    hypothesis: str
    reason: str
    refs: list[str] = Field(default_factory=list)


class RCAFindings(BaseModel):
    summary: str
    root_causes: list[RootCauseFinding]
    rejected_hypotheses: list[RejectedHypothesis] = Field(default_factory=list)
    data_notes: list[str] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)   # filled by the API from the ADK trace


# ---------------------------------------------------------------------------
# Step 5 - Solution Agent (agent)
# ---------------------------------------------------------------------------

class SolutionInput(BaseModel):
    findings: RCAFindings
    listing: ListingInfo
    profile: CategoryProfile


class Fix(BaseModel):
    cause_id: str                               # links back to RootCauseFinding
    fix: str                                    # specific action, e.g. "Change size L length from 72 cm to 69 cm"
    target: str                                 # e.g. "size_chart.L.length", "batch B36", "listing photo 2"
    owner: Owner


class SolutionOutput(BaseModel):
    fixes: list[Fix]


# ---------------------------------------------------------------------------
# Step 6 - Checks and scoring (code)
# ---------------------------------------------------------------------------

class CostModel(BaseModel):
    category: str
    reverse_shipping: float
    restocking: float
    write_off_rate: float
    margin: float


class ScoringInput(BaseModel):
    evidence_pack: EvidencePack
    findings: RCAFindings
    solution: SolutionOutput
    cost_model: CostModel


class Confidence(BaseModel):
    score: int = Field(..., ge=0, le=100)
    level: Literal["high", "medium", "low"]
    breakdown: dict[str, int]                   # share, volume, agreement, photo, contradiction


class Impact(BaseModel):
    extra_returns_per_month: int
    cost_per_return_inr: float
    monthly_cost_inr: float


class CheckReport(BaseModel):
    dropped_evidence: list[str] = Field(default_factory=list)      # refs not found
    number_mismatches: list[str] = Field(default_factory=list)     # numbers not in evidence
    dropped_causes: list[str] = Field(default_factory=list)        # causes left with < 2 evidence
    retried_agent: bool = False


class ReportRootCause(BaseModel):
    cause_id: str
    title: str
    cause: RootCause
    owner: Owner
    evidence: list[EvidenceRef]
    counter_evidence: list[EvidenceRef]
    affected: Affected
    fix: Optional[str] = None                   # None when owner is "none"
    confidence: Confidence
    impact: Impact
    rank: int


class ProductReport(BaseModel):
    product_id: str
    evidence_pack_id: Optional[str] = None      # None for short reports
    status: Literal["analyzed", "not_enough_data", "healthy"]
    period: Period
    summary: str
    metrics: ProductMetrics
    root_causes: list[ReportRootCause] = Field(default_factory=list)
    rejected_hypotheses: list[RejectedHypothesis] = Field(default_factory=list)
    reason_mismatch_share: Optional[float] = None
    top_reasons: list[ReasonShare] = Field(default_factory=list)  # used by short reports
    data_notes: list[str] = Field(default_factory=list)
    checks: CheckReport = Field(default_factory=CheckReport)
    model_version: Optional[str] = None


# ---------------------------------------------------------------------------
# Step 7 - Save and show (code)
# ---------------------------------------------------------------------------

RunStatus = Literal["gathering", "finding_causes", "preparing_fixes", "done", "failed"]


class ReportRun(BaseModel):
    run_id: str
    product_id: str
    status: RunStatus
    error: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None


class ReportResponse(BaseModel):
    """What GET /products/{id}/report (or the run endpoint) returns to the web app."""
    product_id: str
    report_id: Optional[str] = None
    run: Optional[ReportRun] = None             # set while an analysis is running
    report: Optional[ProductReport] = None      # set when done or when a fresh report exists
    built_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Seller question - Q&A Agent (agent) + checks (code)
# ---------------------------------------------------------------------------

class QATurn(BaseModel):
    question: str
    answer: str


class QAInput(BaseModel):
    product_id: str
    session_id: str
    question: str
    report: ProductReport
    evidence_pack: EvidencePack
    history: list[QATurn] = Field(default_factory=list, max_length=5)
    max_tool_calls: int = 5


class QAAnswer(BaseModel):
    """Q&A Agent output."""
    answer: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    related_return_ids: list[str] = Field(default_factory=list)
    enough_data: bool
    tool_results: list[ToolResult] = Field(default_factory=list)   # filled by the API from the ADK trace


class QAResponse(BaseModel):
    """What POST /products/{id}/questions returns after checks."""
    qa_id: str
    product_id: str
    session_id: str
    question: str
    answer: QAAnswer
    checks: CheckReport
    created_at: datetime

