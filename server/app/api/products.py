"""Flow B endpoints: seller product list, product report (background run + polling) and seller Q&A."""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.flow_b import QAResponse, ReportResponse
from app.services.flow_b import qa
from app.services.flow_b.evidence_pack import load_pack
from app.services.flow_b.pipeline import open_report, run_report, run_status

router = APIRouter(tags=["products (Flow B)"])
DB = Annotated[Session, Depends(get_session)]


class QuestionIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    session_id: str | None = Field(default=None, max_length=64)  # omit to start a new conversation


def _seller_of(db: Session, product_id: str) -> str:
    seller = db.execute(text("SELECT seller_id FROM product WHERE id = :p"), {"p": product_id}).scalar()
    if seller is None:
        raise HTTPException(404, "Product not found")
    return seller


@router.get("/sellers")
def list_sellers(db: DB):
    """Sellers for the demo switcher (no login in Phase 1)."""
    return [dict(r) for r in db.execute(text("""
        SELECT s.id, s.name, count(p.id) AS products FROM seller s LEFT JOIN product p ON p.seller_id = s.id
        GROUP BY s.id ORDER BY s.name""")).mappings()]


@router.get("/sellers/{seller_id}/products")
def seller_products(seller_id: str, db: DB):
    """My Products: orders, returns, return rate and top cause (last 90 days, SQL views; no AI),
    plus the saved report's status."""
    if not db.execute(text("SELECT 1 FROM seller WHERE id = :s"), {"s": seller_id}).scalar():
        raise HTTPException(404, "Seller not found")
    rows = db.execute(text("""
        SELECT l.product_id, l.name, l.category, l.orders, l.returns, l.return_rate, l.top_cause,
               b.return_rate AS category_rate, p.report_stale,
               pr.id AS report_id, pr.status AS report_status, pr.created_at AS report_built_at,
               jsonb_array_length(pr.report -> 'root_causes') AS root_causes,
               rr.status AS run_status
        FROM v_seller_product_list l
        JOIN product p ON p.id = l.product_id
        LEFT JOIN v_category_baseline_90d b ON b.category = l.category
        LEFT JOIN product_report pr ON pr.product_id = l.product_id AND pr.is_current
        LEFT JOIN report_run rr ON rr.product_id = l.product_id
              AND rr.status IN ('gathering', 'finding_causes', 'preparing_fixes')
        WHERE l.seller_id = :s ORDER BY l.return_rate DESC, l.product_id"""), {"s": seller_id}).mappings().all()
    return [dict(r) for r in rows]


@router.get("/products/{product_id}/report", response_model=ReportResponse)
def get_report(product_id: str, background: BackgroundTasks, db: DB):
    """Saved report if fresh; otherwise starts (or joins) a run and returns it. Poll the run endpoint every 2-3 s."""
    resp, start = open_report(db, product_id, _seller_of(db, product_id))
    if start:
        background.add_task(run_report, start, product_id)
    return resp


@router.post("/products/{product_id}/report/refresh", response_model=ReportResponse, status_code=202)
def refresh_report(product_id: str, background: BackgroundTasks, db: DB):
    """Force a new analysis (the Refresh button). Joins the active run if one is already going."""
    resp, start = open_report(db, product_id, _seller_of(db, product_id), force=True)
    if start:
        background.add_task(run_report, start, product_id)
    return resp


@router.get("/products/{product_id}/report/runs/{run_id}", response_model=ReportResponse)
def get_run(product_id: str, run_id: str, db: DB):
    """Run progress (gathering -> finding_causes -> preparing_fixes -> done | failed) and the report when done."""
    resp = run_status(db, product_id, run_id)
    if resp is None:
        raise HTTPException(404, "Run not found")
    return resp


@router.get("/products/{product_id}/evidence-packs/{pack_id}")
def get_evidence_pack(product_id: str, pack_id: str, db: DB):
    """The evidence a report cites, so the web app can show what each ref points to."""
    owner = db.execute(text("SELECT product_id FROM evidence_pack WHERE id = :id"), {"id": pack_id}).scalar()
    if owner != product_id:
        raise HTTPException(404, "Evidence pack not found")
    return load_pack(db, pack_id)


@router.post("/products/{product_id}/questions", response_model=QAResponse)
def ask_question(product_id: str, body: QuestionIn, db: DB):
    """Seller Q&A (synchronous). Answers from the saved report and evidence pack; tools only if needed."""
    try:
        return qa.ask(db, product_id, body.question.strip(), body.session_id)
    except qa.QAError as e:
        raise HTTPException(e.status, str(e))


@router.get("/products/{product_id}/questions")
def question_history(product_id: str, session_id: str, db: DB):
    """Q&A history of one conversation, oldest first."""
    _seller_of(db, product_id)
    return qa.history(db, product_id, session_id)
