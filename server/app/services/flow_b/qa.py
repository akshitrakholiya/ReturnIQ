"""Flow B seller Q&A (synchronous): saved report + evidence pack + last 5 turns -> Q&A Agent -> checks -> save."""
import asyncio
import json
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.flow_b_agents import QA
from app.agents.runner import context_message, run_agent
from app.core.config import settings
from app.schemas.flow_b import (CheckReport, EvidencePackInput, HealthCheckInput, ProductReport, QAAnswer, QAInput,
                                QAResponse, QATurn)
from app.services.flow_b import checks
from app.services.flow_b.evidence_pack import build_evidence_pack, load_pack
from app.services.flow_b.health import health_check
from app.services.flow_b.pipeline import record_agent_run

HISTORY_TURNS = 5


class QAError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _history(db: Session, product_id: str, session_id: str) -> list[QATurn]:
    rows = db.execute(text("""SELECT question, answer ->> 'answer' AS answer FROM product_qa
                              WHERE product_id = :p AND session_id = :s ORDER BY created_at DESC LIMIT :n"""),
                      {"p": product_id, "s": session_id, "n": HISTORY_TURNS}).all()
    return [QATurn(question=r.question, answer=r.answer or "") for r in reversed(rows)]


def ask(db: Session, product_id: str, question: str, session_id: str | None) -> QAResponse:
    row = db.execute(text("""SELECT pr.report, pr.evidence_pack_id, p.category FROM product p
                             LEFT JOIN product_report pr ON pr.product_id = p.id AND pr.is_current
                             WHERE p.id = :p"""), {"p": product_id}).mappings().first()
    if not row:
        raise QAError(404, "Product not found")
    if row["report"] is None:
        raise QAError(409, "No report for this product yet; open the report first")
    report = ProductReport.model_validate(row["report"])
    if row["evidence_pack_id"]:
        pack = load_pack(db, row["evidence_pack_id"])
    else:  # short reports (healthy / not enough data) have no pack: build one, it is plain code
        health, raw = health_check(HealthCheckInput(product_id=product_id, category=row["category"], period=report.period))
        pack = build_evidence_pack(db, EvidencePackInput(product_id=product_id, category=row["category"],
                                                         period=report.period), health.metrics, raw["root_cause"])
    session_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
    inp = QAInput(product_id=product_id, session_id=session_id, question=question, report=report,
                  evidence_pack=pack, history=_history(db, product_id, session_id),
                  max_tool_calls=settings.max_qa_tool_calls)

    def wrong(a: QAAnswer, tools) -> list[str]:
        allowed = checks.evidence_numbers(pack, tools, report.model_dump(mode="json"), question)
        return checks.wrong_numbers([a.answer, *(e.finding for e in a.evidence)], allowed)

    result = asyncio.run(run_agent(QA, product_id, context_message("Answer the seller's question.",
                                                                     inp.model_dump(mode="json")), QAAnswer, wrong))
    if result.output is None:
        record_agent_run(db, "qa", product_id, result)
        db.commit()
        raise QAError(503, f"Could not answer right now: {result.error}")

    # checks: citations, numbers, related returns must belong to this product
    answer: QAAnswer = result.output
    report_checks = CheckReport(retried_agent=result.retried)
    refs = checks.known_refs(pack, result.tool_results)
    allowed = checks.evidence_numbers(pack, result.tool_results, report.model_dump(mode="json"), question)
    evidence, dropped = checks.keep_cited(answer.evidence, refs)
    evidence, bad_e = checks.keep_numbers(evidence, allowed)
    text_, bad_a = checks.strip_sentences(answer.answer, allowed)
    report_checks.dropped_evidence = dropped
    report_checks.number_mismatches = sorted(set(bad_e + bad_a), key=float)
    related = set(db.execute(text("SELECT id FROM returns WHERE product_id = :p AND id = ANY(:ids)"),
                             {"p": product_id, "ids": answer.related_return_ids}).scalars())
    answer = answer.model_copy(update=dict(
        answer=text_ or "I could not verify the numbers for that answer; please rephrase the question.",
        evidence=evidence, related_return_ids=[r for r in answer.related_return_ids if r in related],
        enough_data=answer.enough_data and bool(text_), tool_results=result.tool_results))

    run_id = record_agent_run(db, "qa", product_id, result)
    qa = db.execute(text("""INSERT INTO product_qa (product_id, session_id, question, answer, tool_calls)
                            VALUES (:p, :s, :q, CAST(:a AS jsonb), CAST(:t AS jsonb)) RETURNING id, created_at"""),
                    dict(p=product_id, s=session_id, q=question, a=answer.model_dump_json(),
                         t=json.dumps({"agent_run_id": run_id, "calls": result.trace}, default=str))).one()
    db.commit()
    return QAResponse(qa_id=qa.id, product_id=product_id, session_id=session_id, question=question, answer=answer,
                      checks=report_checks, created_at=qa.created_at)


def history(db: Session, product_id: str, session_id: str) -> list[dict]:
    rows = db.execute(text("""SELECT id AS qa_id, session_id, question, answer, created_at FROM product_qa
                              WHERE product_id = :p AND session_id = :s ORDER BY created_at"""),
                      {"p": product_id, "s": session_id}).mappings().all()
    return [dict(r) for r in rows]
