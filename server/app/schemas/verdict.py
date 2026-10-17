from typing import Literal

from pydantic import BaseModel, Field

RootCause = Literal["size_fit", "defect_quality", "damaged_in_transit", "wrong_item",
                    "not_as_described", "changed_mind", "suspicious", "other"]
Action = Literal["approve_return", "request_more_evidence", "reject_return", "manual_review"]


class EvidenceItem(BaseModel):
    ref: str
    finding: str


class MediaFindingsSummary(BaseModel):
    defect_type: str | None = None
    severity: Literal["none", "low", "medium", "high"] = "none"
    visible_damage: bool = False
    matches_listing: bool | None = None


class ReturnVerdict(BaseModel):
    """The Return Agent's JSON output (LLD: ReturnVerdict)."""
    root_cause: RootCause
    stated_reason: str
    reason_mismatch: bool
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=1)
    evidence: list[EvidenceItem]
    media_findings: MediaFindingsSummary | None = None
    recommended_action: Action
    needs_manual_review: bool
