"""Flow B report pipeline: background job per product (same pattern as Flow A's analysis.py).

gathering (health check + evidence pack) -> finding_causes (RCA Agent) -> preparing_fixes (Solution Agent,
checks and scoring) -> done | failed. Only the API writes; one active run per product (advisory lock +
partial unique index on report_run).
"""
import asyncio
import json
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.flow_b_agents import RCA, SOLUTION
from app.agents.runner import AgentResult, context_message, run_agent
from app.core.config import settings
from app.db.session import SessionLocal
from app.schemas.flow_b import (CostModel, EvidencePack, EvidencePackInput, HealthCheckInput, ProductReport,
                                RCAFindings, RCAInput, ReportRequest, ReportResponse, ReportRun, SolutionInput,
                                SolutionOutput, ToolResult)
from app.services.flow_b import checks
from app.services.flow_b.evidence_pack import build_evidence_pack
from app.services.flow_b.health import cache_check, health_check, reviewed_count
from app.services.flow_b.scoring import build_report, short_report

log = logging.getLogger(__name__)
ACTIVE = ("gathering", "finding_causes", "preparing_fixes")
PERIOD = "last_90d"


# ───────────── runs ─────────────
def start_run(db: Session, product_id: str) -> tuple[dict, bool]:
    """Return (run, created). Reuses the product's active run; expires runs left behind by a restart."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('report:' || :p))"), {"p": product_id})
    db.execute(text("""UPDATE report_run SET status = 'failed', finished_at = now(),
                              error = 'run did not finish (server restarted?)'
                       WHERE product_id = :p AND status = ANY(CAST(:a AS report_run_status[]))
                         AND started_at < now() - make_interval(mins => :m)"""),
               {"p": product_id, "a": list(ACTIVE), "m": settings.report_run_timeout_minutes})
    run = db.execute(text("""SELECT * FROM report_run WHERE product_id = :p
                             AND status = ANY(CAST(:a AS report_run_status[]))"""),
                     {"p": product_id, "a": list(ACTIVE)}).mappings().first()
    created = run is None
    if created:
        run = db.execute(text("INSERT INTO report_run (product_id) VALUES (:p) RETURNING *"),
                         {"p": product_id}).mappings().one()
    db.commit()
    return dict(run), created


def _status(run_id: str, status: str, error: str | None = None, report_id: str | None = None) -> None:
    with SessionLocal() as db:
        db.execute(text("""UPDATE report_run SET status = CAST(:s AS report_run_status), error = :e,
                                  report_id = COALESCE(:r, report_id),
                                  finished_at = CASE WHEN :s IN ('done', 'failed') THEN now() END
                           WHERE id = :id"""), {"id": run_id, "s": status, "e": error, "r": report_id})
        db.commit()


def run_report(run_id: str, product_id: str) -> None:
    """Entry point for FastAPI background tasks (sync)."""
    try:
        asyncio.run(_build(run_id, product_id))
    except Exception as e:  # never leave a run stuck in an active status
        log.exception("report run %s crashed", run_id)
        _status(run_id, "failed", f"internal error: {type(e).__name__}: {str(e)[:200]}")


# ───────────── the pipeline ─────────────
def rca_wrong_numbers(pack: EvidencePack):
    def check(f: RCAFindings, tool_results: list[ToolResult]) -> list[str]:
        texts = [f.summary, *(h.reason for h in f.rejected_hypotheses)]
        for rc in f.root_causes:
            texts += [rc.title, *(e.finding for e in rc.evidence + rc.counter_evidence)]
        return checks.wrong_numbers(texts, checks.evidence_numbers(pack, tool_results))
    return check


def solution_wrong_numbers(pack: EvidencePack, rca_tools: list[ToolResult]):
    def check(s: SolutionOutput, _tools) -> list[str]:
        return checks.wrong_numbers([f.fix for f in s.fixes], checks.evidence_numbers(pack, rca_tools))
    return check


async def _build(run_id: str, product_id: str) -> None:
    with SessionLocal() as db:
        product = db.execute(text("SELECT id, category FROM product WHERE id = :p"), {"p": product_id}).mappings().one()
        health, raw = health_check(HealthCheckInput(product_id=product_id, category=product["category"], period=PERIOD))
        if health.decision != "analyze":
            report_id = _save(db, run_id, short_report(product_id, health.decision, health, PERIOD), [])
            log.info("report %s for %s: %s (no agents)", report_id, product_id, health.decision)
            return
        pack = build_evidence_pack(db, EvidencePackInput(product_id=product_id, category=product["category"],
                                                         period=PERIOD), health.metrics, raw["root_cause"])
        cost_row = db.execute(text("SELECT * FROM cost_model WHERE category = :c"), {"c": product["category"]}).mappings().first()
        cost = CostModel(**{k: float(v) if k != "category" else v for k, v in cost_row.items()}) if cost_row else None

    _status(run_id, "finding_causes")
    rca = await run_agent(RCA, product_id,
                          context_message("Find the root causes of this product's returns.",
                                          RCAInput(evidence_pack=pack, max_tool_calls=settings.max_rca_tool_calls).model_dump(mode="json")),
                          RCAFindings, rca_wrong_numbers(pack))
    runs = [rca]
    if rca.output is None:
        _record(product_id, [rca])
        _status(run_id, "failed", f"root-cause step failed: {rca.error}")
        return
    findings: RCAFindings = rca.output
    findings.tool_results = rca.tool_results

    _status(run_id, "preparing_fixes")
    solution = None
    notes = []
    owned = [rc for rc in findings.root_causes if rc.owner != "none"]
    if owned:
        sol = await run_agent(SOLUTION, product_id,
                              context_message("Write one specific fix per root cause.",
                                              SolutionInput(findings=findings, listing=pack.listing,
                                                            profile=pack.profile).model_dump(mode="json")),
                              SolutionOutput, solution_wrong_numbers(pack, rca.tool_results))
        runs.append(sol)
        solution = sol.output
        if solution is None:
            notes.append("Fixes unavailable: the fix step failed; root causes are still valid")

    report = build_report(pack, findings, solution, cost, rca.tool_results, any(r.retried for r in runs),
                          " + ".join(dict.fromkeys(r.model for r in runs)), notes)
    with SessionLocal() as db:
        report_id = _save(db, run_id, report, runs)
    log.info("report %s for %s: %d root cause(s), checks=%s", report_id, product_id, len(report.root_causes),
             report.checks.model_dump())


# ───────────── persistence (the only place Flow B reports write) ─────────────
def record_agent_run(db: Session, agent: str, product_id: str, r: AgentResult) -> str:
    """ADK trace of one agent run (shared with Q&A). The caller commits."""
    return db.execute(text("""
        INSERT INTO agent_run (agent, subject_type, subject_id, status, model, tool_calls, raw_output, error,
                               tokens_in, tokens_out, finished_at)
        VALUES (CAST(:a AS agent_name), 'product', :p, CAST(:s AS run_status), :m, CAST(:t AS jsonb),
                CAST(:o AS jsonb), :e, :ti, :to, now()) RETURNING id"""),
        dict(a=agent, p=product_id, s="succeeded" if r.output is not None else "failed", m=r.model,
             t=json.dumps(r.trace, default=str),
             o=json.dumps({"output": r.output.model_dump(mode="json") if r.output else None,
                           "duration_ms": r.duration_ms, "retried": r.retried}, default=str),
             e=r.error, ti=r.tokens[0], to=r.tokens[1])).scalar_one()


def _record(product_id: str, runs: list[AgentResult], db: Session | None = None) -> None:
    """rca (+ solution) traces. Commits itself only when it opened the session."""
    if db is not None:
        for r, name in zip(runs, ("rca", "solution")):
            record_agent_run(db, name, product_id, r)
        return
    with SessionLocal() as own:
        _record(product_id, runs, own)
        own.commit()


def _save(db: Session, run_id: str, report: ProductReport, runs: list[AgentResult]) -> str:
    """One transaction: agent traces, report (flips the old one), run done, product no longer stale."""
    _record(report.product_id, runs, db)
    db.execute(text("UPDATE product_report SET is_current = false WHERE product_id = :p AND is_current"),
               {"p": report.product_id})
    report_id = db.execute(text("""
        INSERT INTO product_report (product_id, evidence_pack_id, status, report, returns_count_at_build, model_version)
        VALUES (:p, :pack, CAST(:s AS report_status), CAST(:r AS jsonb), :n, :m) RETURNING id"""),
        dict(p=report.product_id, pack=report.evidence_pack_id, s=report.status,
             r=report.model_dump_json(), n=reviewed_count(db, report.product_id),
             m=report.model_version)).scalar_one()
    db.execute(text("""UPDATE report_run SET status = 'done', report_id = :r, error = NULL, finished_at = now()
                       WHERE id = :id"""), {"r": report_id, "id": run_id})
    db.execute(text("UPDATE product SET report_stale = false WHERE id = :p"), {"p": report.product_id})
    db.commit()
    return report_id


# ───────────── what the web app reads ─────────────
def _run_model(run: dict) -> ReportRun:
    return ReportRun(run_id=run["id"], product_id=run["product_id"], status=run["status"], error=run["error"],
                     started_at=run["started_at"], finished_at=run["finished_at"])


def report_by_id(db: Session, report_id: str) -> tuple[ProductReport, object] | None:
    row = db.execute(text("SELECT report, created_at FROM product_report WHERE id = :id"), {"id": report_id}).first()
    return (ProductReport.model_validate(row.report), row.created_at) if row else None


def open_report(db: Session, product_id: str, seller_id: str, force: bool = False) -> tuple[ReportResponse, str | None]:
    """GET /products/{id}/report and refresh. Returns (response, run_id to start in the background or None)."""
    cache = cache_check(db, ReportRequest(product_id=product_id, seller_id=seller_id, force_refresh=force))
    active = db.execute(text("""SELECT * FROM report_run WHERE product_id = :p
                                AND status = ANY(CAST(:a AS report_run_status[]))"""),
                        {"p": product_id, "a": list(ACTIVE)}).mappings().first()
    if cache.status == "fresh" and not active:
        report, built = report_by_id(db, cache.report_id)
        if cache.new_reviewed_returns:
            report.data_notes.append(f"{cache.new_reviewed_returns} new reviewed return(s) since this analysis; "
                                     f"it is rebuilt after {settings.report_rebuild_min_reviews}")
        return ReportResponse(product_id=product_id, report_id=cache.report_id, report=report, built_at=built), None
    run, created = start_run(db, product_id)
    return ReportResponse(product_id=product_id, run=_run_model(run)), run["id"] if created else None


def run_status(db: Session, product_id: str, run_id: str) -> ReportResponse | None:
    run = db.execute(text("SELECT * FROM report_run WHERE id = :id AND product_id = :p"),
                     {"id": run_id, "p": product_id}).mappings().first()
    if not run:
        return None
    resp = ReportResponse(product_id=product_id, run=_run_model(dict(run)))
    if run["status"] == "done" and run["report_id"]:
        resp.report_id = run["report_id"]
        resp.report, resp.built_at = report_by_id(db, run["report_id"])
    return resp
