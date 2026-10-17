from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.verdict import RootCause

# 'suspicious' is never a customer-stated reason (DB CHECK enforces it too).
StatedReason = Literal["size_fit", "defect_quality", "damaged_in_transit", "wrong_item",
                       "not_as_described", "changed_mind", "other"]


class MediaIn(BaseModel):
    storage_url: str  # the value returned by POST /media/upload-url


class ReturnCreate(BaseModel):
    order_id: str
    stated_reason: StatedReason
    comment: str | None = Field(default=None, max_length=1000)
    media: list[MediaIn] = Field(default_factory=list)


class ReturnCreated(BaseModel):
    return_id: str
    status: str
    media_count: int


class ReviewIn(BaseModel):
    decision: Literal["accepted", "rejected"]  # accept or reject the AI verdict
    final_root_cause: RootCause | None = None   # optional on accept (defaults to the AI cause)
    note: str | None = Field(default=None, max_length=1000)
    reviewer: str = Field(min_length=1, max_length=100)  # no login in Phase 1; the reviewer's name


class ReviewSaved(BaseModel):
    return_id: str
    status: str
    decision: str
    final_root_cause: RootCause
    ai_root_cause: RootCause | None
    product_id: str
    report_stale: bool
