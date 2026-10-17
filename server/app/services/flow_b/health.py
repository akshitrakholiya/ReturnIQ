"""Flow B steps 1-2 (code): cache check and health check. No AI runs here."""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.flow_b import (CacheCheckResult, HealthCheckInput, HealthCheckResult, ProductMetrics,
                                ReasonShare, ReportRequest)
from app.tools.product_intelligence import NOT_ANALYZED, category_baseline, product_history, return_breakdown


def reviewed_count(db: Session, product_id: str) -> int:
    return db.execute(text("""SELECT count(*) FROM return_review rv JOIN returns r ON r.id = rv.return_id
                              WHERE r.product_id = :p"""), {"p": product_id}).scalar_one()


def cache_check(db: Session, req: ReportRequest) -> CacheCheckResult:
    """fresh -> show the saved report. stale/missing -> build. A review marks the product stale
    (Flow A); the report is rebuilt only once enough new reviewed returns exist."""
    cur = db.execute(text("""SELECT pr.id, pr.returns_count_at_build, p.report_stale
                             FROM product p LEFT JOIN product_report pr ON pr.product_id = p.id AND pr.is_current
                             WHERE p.id = :p"""), {"p": req.product_id}).mappings().first()
    if not cur or cur["id"] is None:
        return CacheCheckResult(status="missing")
    new = max(reviewed_count(db, req.product_id) - cur["returns_count_at_build"], 0)
    stale = req.force_refresh or (cur["report_stale"] and new >= settings.report_rebuild_min_reviews)
    return CacheCheckResult(status="stale" if stale else "fresh", report_id=cur["id"], new_reviewed_returns=new)


def metrics_for(product_id: str, category: str, period: str = "last_90d") -> tuple[ProductMetrics, dict]:
    hist = product_history(product_id, period, "previous")
    base = category_baseline(category, period)
    metrics = ProductMetrics(orders=hist["orders"], returns=hist["returns"], return_rate=hist["return_rate"],
                             previous_return_rate=hist["previous"]["return_rate"],
                             category_rate=base["return_rate"], trend=hist["trend"])
    return metrics, {"history": hist, "baseline": base}


def top_reasons(breakdown_rows: list[dict], n: int = 3) -> list[ReasonShare]:
    return [ReasonShare(cause=r["group"], count=r["count"], share=r["share"])
            for r in breakdown_rows if r["group"] != NOT_ANALYZED and r["count"] > 0][:n]


def health_check(inp: HealthCheckInput) -> tuple[HealthCheckResult, dict]:
    """not_enough_data (< 5 returns) / healthy (rate <= 1.2x category and not rising) / analyze."""
    metrics, raw = metrics_for(inp.product_id, inp.category, inp.period)
    causes = return_breakdown(inp.product_id, "root_cause", period=inp.period)
    if metrics.returns < settings.min_returns_for_analysis:
        decision = "not_enough_data"
    elif (metrics.return_rate <= settings.healthy_rate_multiplier * metrics.category_rate
          and metrics.trend != "rising"):
        decision = "healthy"
    else:
        decision = "analyze"
    return HealthCheckResult(decision=decision, metrics=metrics, top_reasons=top_reasons(causes["rows"])), \
        raw | {"root_cause": causes}
