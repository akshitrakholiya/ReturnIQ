import mimetypes
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_session
from app.schemas.returns import ReturnCreate, ReturnCreated, ReviewIn, ReviewSaved
from app.services.analysis import run_return_analysis
from app.services.context_builder import ContextError, build_return_context
from app.services.storage import EXT_INFO, storage

router = APIRouter(prefix="/returns", tags=["returns"])
DB = Annotated[Session, Depends(get_session)]
STATUSES = {"pending_analysis", "analyzing", "awaiting_review", "reviewed", "analysis_failed"}


def _validate_media(items) -> list[dict]:
    if len(items) > settings.max_media_files:
        raise HTTPException(422, f"At most {settings.max_media_files} media files per return")
    rows, seen = [], set()
    for m in items:
        key = storage.key_from_url(m.storage_url)
        if key is None or not storage.exists(key):
            raise HTTPException(422, f"Media not uploaded or not from our storage: {m.storage_url}")
        if key in seen:
            raise HTTPException(422, f"Duplicate media: {m.storage_url}")
        seen.add(key)
        mime, mtype = EXT_INFO[key.rsplit(".", 1)[-1]]
        rows.append(dict(type=mtype, storage_url=m.storage_url, mime_type=mime, size_bytes=storage.size(key)))
    return rows


@router.post("", status_code=201, response_model=ReturnCreated)
def create_return(body: ReturnCreate, background: BackgroundTasks, db: DB):
    """Intake: save the return + media rows, reply 'submitted', start analysis in the background."""
    order = db.execute(text("SELECT id, product_id, customer_id FROM orders WHERE id = :id"),
                       {"id": body.order_id}).mappings().first()
    if not order:
        raise HTTPException(404, "Order not found")
    media = _validate_media(body.media)
    try:
        return_id = db.execute(text("""
            INSERT INTO returns (order_id, product_id, customer_id, stated_reason, comment)
            VALUES (:order_id, :product_id, :customer_id, CAST(:reason AS root_cause), :comment)
            RETURNING id"""),
            dict(order_id=order["id"], product_id=order["product_id"], customer_id=order["customer_id"],
                 reason=body.stated_reason, comment=body.comment)).scalar_one()
    except IntegrityError:  # returns.order_id is UNIQUE: one return per order
        db.rollback()
        raise HTTPException(409, "A return already exists for this order")
    for m in media:
        db.execute(text("""INSERT INTO return_media (return_id, type, storage_url, mime_type, size_bytes)
                           VALUES (:rid, CAST(:type AS media_type), :storage_url, :mime_type, :size_bytes)"""),
                   dict(rid=return_id, **m))
    db.commit()
    background.add_task(run_return_analysis, return_id)
    return ReturnCreated(return_id=return_id, status="pending_analysis", media_count=len(media))


@router.get("")
def list_returns(db: DB, status: str | None = None, limit: int = Query(50, le=200), offset: int = 0):
    """Reviewer queue. status=awaiting_review also includes analysis_failed (needs a manual decision)."""
    if status is not None and status not in STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(STATUSES)}")
    statuses = ["awaiting_review", "analysis_failed"] if status == "awaiting_review" else ([status] if status else list(STATUSES))
    rows = db.execute(text("""
        SELECT r.id, r.status, r.stated_reason, r.created_at, p.name AS product_name,
               ra.root_cause AS ai_root_cause, ra.confidence, ra.needs_manual_review,
               (SELECT count(*) FROM return_media m WHERE m.return_id = r.id) AS media_count
        FROM returns r
        JOIN product p ON p.id = r.product_id
        LEFT JOIN return_analysis ra ON ra.return_id = r.id AND ra.is_current
        WHERE r.status = ANY(CAST(:statuses AS return_status[]))
        ORDER BY r.created_at DESC LIMIT :limit OFFSET :offset"""),
        dict(statuses=statuses, limit=limit, offset=offset)).mappings().all()
    return [dict(r) for r in rows]


@router.post("/{return_id}/review", response_model=ReviewSaved)
def review_return(return_id: str, body: ReviewIn, db: DB):
    """Human decision. Saves return_review, marks the return reviewed and the product's report stale."""
    # Lock the return so two reviewers cannot both decide it.
    ret = db.execute(text("SELECT id, status, product_id FROM returns WHERE id = :id FOR UPDATE"),
                     {"id": return_id}).mappings().first()
    if not ret:
        raise HTTPException(404, "Return not found")
    if ret["status"] not in ("awaiting_review", "analysis_failed"):
        db.rollback()
        raise HTTPException(409, f"Return is '{ret['status']}'; only awaiting_review or analysis_failed can be reviewed")
    ai = db.execute(text("SELECT id, root_cause FROM return_analysis WHERE return_id = :id AND is_current"),
                    {"id": return_id}).mappings().first()

    final = body.final_root_cause
    if ai is None:  # analysis_failed: nothing to accept, so the reviewer must say what the cause is
        if final is None:
            db.rollback()
            raise HTTPException(422, "No AI verdict exists for this return; final_root_cause is required")
    elif body.decision == "accepted":
        if final is not None and final != ai["root_cause"]:
            db.rollback()
            raise HTTPException(422, f"Accepting means keeping the AI cause '{ai['root_cause']}'; reject to choose another")
        final = ai["root_cause"]
    else:  # rejected
        if final is None or final == ai["root_cause"]:
            db.rollback()
            raise HTTPException(422, f"Rejecting requires a final_root_cause different from the AI cause '{ai['root_cause']}'")

    db.execute(text("""INSERT INTO return_review (return_id, analysis_id, decision, final_root_cause, note, reviewer)
                       VALUES (:r, :a, CAST(:d AS review_decision), CAST(:c AS root_cause), :n, :who)"""),
               dict(r=return_id, a=ai["id"] if ai else None, d=body.decision, c=final, n=body.note, who=body.reviewer))
    db.execute(text("UPDATE returns SET status = 'reviewed' WHERE id = :id"), {"id": return_id})
    db.execute(text("UPDATE product SET report_stale = true WHERE id = :p"), {"p": ret["product_id"]})
    db.commit()
    return ReviewSaved(return_id=return_id, status="reviewed", decision=body.decision, final_root_cause=final,
                       ai_root_cause=ai["root_cause"] if ai else None, product_id=ret["product_id"], report_stale=True)


@router.post("/{return_id}/reanalyze", status_code=202)
def reanalyze_return(return_id: str, background: BackgroundTasks, db: DB):
    """Rerun analysis after a failure or new media. History is kept; the new analysis becomes current."""
    status = db.execute(text("SELECT status FROM returns WHERE id = :id"), {"id": return_id}).scalar()
    if status is None:
        raise HTTPException(404, "Return not found")
    if status not in ("analysis_failed", "awaiting_review", "pending_analysis"):
        raise HTTPException(409, f"Cannot reanalyze a return that is '{status}'")
    background.add_task(run_return_analysis, return_id)
    return {"return_id": return_id, "status": "analysis queued"}


@router.get("/{return_id}/context")
def get_return_context(return_id: str):
    """Dev/debug: the exact context the Return Agent will receive (no writes, no PII)."""
    try:
        return build_return_context(return_id)
    except ContextError as e:
        raise HTTPException(404, str(e))


@router.get("/{return_id}")
def get_return(return_id: str, db: DB):
    """Everything the review screen needs: return, order context, media, AI verdict, review."""
    r = db.execute(text("""
        SELECT r.id, r.status, r.stated_reason, r.comment, r.created_at, r.status_updated_at,
               r.order_id, r.product_id, p.name AS product_name, p.category,
               o.variant, o.batch_id, o.price, o.order_date
        FROM returns r JOIN product p ON p.id = r.product_id JOIN orders o ON o.id = r.order_id
        WHERE r.id = :id"""), {"id": return_id}).mappings().first()
    if not r:
        raise HTTPException(404, "Return not found")
    media = [dict(m) | {"view_url": storage.view_url(m["storage_url"])} for m in db.execute(text(
        "SELECT id, type, storage_url, mime_type, size_bytes FROM return_media WHERE return_id = :id ORDER BY id"),
        {"id": return_id}).mappings()]
    listing = db.execute(text("SELECT listing_image_urls FROM product WHERE id = :p"), {"p": r["product_id"]}).scalar() or []
    analysis = db.execute(text("""
        SELECT id, root_cause, reason_mismatch, confidence, explanation, evidence, context_notes,
               recommended_action, needs_manual_review, model_version, created_at
        FROM return_analysis WHERE return_id = :id AND is_current"""), {"id": return_id}).mappings().first()
    findings = []
    if analysis:
        findings = [dict(f) for f in db.execute(text("""
            SELECT id, media_id, defect_type, severity, visible_damage, matches_listing, description
            FROM media_finding WHERE analysis_id = :a ORDER BY id"""), {"a": analysis["id"]}).mappings()]
    review = db.execute(text("""SELECT decision, final_root_cause, note, reviewer, reviewed_at
                                FROM return_review WHERE return_id = :id"""), {"id": return_id}).mappings().first()
    return dict(r) | {"listing_images": [{"storage_url": u, "view_url": storage.view_url(u)} for u in listing],
                      "media": media, "analysis": dict(analysis) if analysis else None,
                      "media_findings": findings, "review": dict(review) if review else None}
