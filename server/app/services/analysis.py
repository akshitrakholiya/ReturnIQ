"""Flow A background job: gather (code) -> Return Agent -> validate/check (code) -> save (API only)."""
import asyncio
import json
import logging
import re
import time

from pydantic import ValidationError
from sqlalchemy import text

from app.agents.return_agent import (ReturnAgentSession, TurnResult, first_message, parse_json,
                                     retry_message)
from app.core.config import gemini_chain, settings
from app.db.session import SessionLocal
from app.schemas.verdict import ReturnVerdict
from app.services.checks import check_verdict, wrong_numbers
from app.services.context_builder import ContextError, build_return_context

log = logging.getLogger(__name__)
OUTPUT_RETRIES = 1  # one retry with feedback for invalid JSON or wrong numbers; infra errors fail over instead
ANALYZABLE = ("pending_analysis", "analysis_failed", "awaiting_review")  # awaiting_review = reanalysis


def _quota_wait_seconds(e: Exception) -> float | None:
    """Seconds Gemini asks us to wait after a 429 ('Please retry in 49.7s'), capped at 90 s."""
    msg = str(e)
    if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg:
        return None
    m = re.search(r"retry in ([\d.]+)s", msg) or re.search(r"retryDelay['\"]?: ?['\"]?(\d+)s", msg)
    return min(float(m.group(1)) + 1, 90) if m else 30


def run_return_analysis(return_id: str) -> None:
    """Entry point for FastAPI background tasks (sync)."""
    state: dict = {}
    try:
        asyncio.run(_analyze(return_id, state))
    except Exception as e:  # never leave the return stuck in 'analyzing' or the run stuck in 'running'
        log.exception("analysis crashed for %s", return_id)
        _mark_failed(return_id, state.get("run_id"), f"internal error: {type(e).__name__}: {str(e)[:200]}")


async def _analyze(return_id: str, state: dict) -> None:
    with SessionLocal() as db:
        moved = db.execute(text("UPDATE returns SET status = 'analyzing' WHERE id = :id AND status = ANY(CAST(:ok AS return_status[]))"),
                           {"id": return_id, "ok": list(ANALYZABLE)}).rowcount
        db.commit()
    if not moved:
        log.warning("%s is not in a state that can be analyzed", return_id)
        return

    try:
        context = build_return_context(return_id)
    except ContextError as e:
        _mark_failed(return_id, None, f"context: {e}")
        return

    models = gemini_chain(settings.return_models)  # (model, key): each model on every key, then the next model
    mi = 0
    session = ReturnAgentSession(*models[mi])
    run_id = state["run_id"] = _start_run(return_id, session.model_name)
    started = time.perf_counter()
    trace: list[dict] = []
    tool_results: list[dict] = []
    tokens_in = tokens_out = None
    message, verdict, error = first_message(context), None, None
    output_retries = 0

    for attempt in range(len(models) + OUTPUT_RETRIES):
        last = attempt == len(models) + OUTPUT_RETRIES - 1
        try:
            res: TurnResult = await asyncio.wait_for(session.send(message), settings.llm_timeout_seconds)
        except Exception as e:  # timeout, quota (429), 5xx: the model is the problem, not the output
            error = (f"model timeout (> {settings.llm_timeout_seconds} s)" if isinstance(e, asyncio.TimeoutError)
                     else f"{type(e).__name__}: {str(e)[:300]}")
            log.warning("%s (%s) failed for %s: %s", session.model_name, session.key_label, return_id, error[:160])
            if last:
                break
            if mi + 1 < len(models):
                mi += 1  # fail over to the next model
                log.warning("failing over to %s", models[mi][0])
            elif (wait := _quota_wait_seconds(e)):
                await asyncio.sleep(wait)  # no model left: wait out the quota window once
            session, message = ReturnAgentSession(*models[mi]), first_message(context)  # fresh session
            continue
        trace += res.tool_calls
        tool_results += res.tool_results
        if res.tokens_in is not None:
            tokens_in, tokens_out = (tokens_in or 0) + res.tokens_in, (tokens_out or 0) + (res.tokens_out or 0)
        try:
            verdict = ReturnVerdict.model_validate(parse_json(res.text))
        except (ValueError, ValidationError) as e:  # json.JSONDecodeError is a ValueError
            error, verdict = f"invalid output: {e}", None
            if output_retries >= OUTPUT_RETRIES or last:
                break
            output_retries += 1
            message = retry_message(str(e)[:500])
            continue
        bad = wrong_numbers(verdict, context, tool_results)
        if bad and output_retries < OUTPUT_RETRIES and not last:
            output_retries += 1
            error = f"numbers not found in evidence: {bad}"
            message = retry_message(f"these numbers do not appear in the evidence: {bad}. Remove or correct them.")
            continue
        error = None  # accepted (leftover wrong numbers are stripped by check_verdict)
        break

    if verdict is None or error:
        _mark_failed(return_id, run_id, error or "no verdict", trace=trace, tokens=(tokens_in, tokens_out), model=session.model_name)
        return

    checked, fixes = check_verdict(verdict, context, tool_results)
    _save(return_id, run_id, checked, fixes, context, tool_results, trace, (tokens_in, tokens_out),
          session.model_name, int((time.perf_counter() - started) * 1000))
    log.info("analysis saved for %s: %s (%.2f)%s", return_id, checked["root_cause"], checked["confidence"],
             f" fixes={fixes}" if fixes else "")


def expire_stuck_analyses(return_id: str | None = None, all_running: bool = False) -> int:
    """Background tasks die with the server process, leaving returns in 'analyzing' forever.
    Moves such returns to 'analysis_failed' (reviewer decides manually or reanalyzes).
    all_running=True (server startup): every 'analyzing' return is dead, whatever its age."""
    with SessionLocal() as db:
        ids = db.execute(text("""
            UPDATE returns SET status = 'analysis_failed'
            WHERE status = 'analyzing' AND (CAST(:id AS text) IS NULL OR id = :id)
              AND (:all OR status_updated_at < now() - make_interval(mins => :m))
            RETURNING id"""), {"id": return_id, "all": all_running, "m": settings.analysis_timeout_minutes}).scalars().all()
        if ids:
            db.execute(text("""UPDATE agent_run SET status = 'failed', finished_at = now(),
                                      error = 'analysis did not finish (server restarted?)'
                               WHERE agent = 'return' AND subject_id = ANY(:ids) AND status = 'running'"""), {"ids": list(ids)})
        db.commit()
    for rid in ids:
        log.warning("analysis of %s did not finish; marked analysis_failed", rid)
    return len(ids)


# ───────────── persistence (the only place Flow A analysis writes) ─────────────
def _start_run(return_id: str, model: str) -> str:
    with SessionLocal() as db:
        rid = db.execute(text("""INSERT INTO agent_run (agent, subject_type, subject_id, model)
                                 VALUES ('return', 'return', :s, :m) RETURNING id"""), {"s": return_id, "m": model}).scalar_one()
        db.commit()
    return rid


def _mark_failed(return_id: str, run_id: str | None, error: str, trace=None, tokens=(None, None), model=None) -> None:
    with SessionLocal() as db:
        if run_id:
            db.execute(text("""UPDATE agent_run SET status = 'failed', error = :e, finished_at = now(), model = COALESCE(:m, model),
                               tool_calls = CAST(:t AS jsonb), tokens_in = :ti, tokens_out = :to WHERE id = :id"""),
                       {"m": model, "e": error, "id": run_id, "t": json.dumps(trace or []), "ti": tokens[0], "to": tokens[1]})
        db.execute(text("UPDATE returns SET status = 'analysis_failed' WHERE id = :id AND status = 'analyzing'"), {"id": return_id})
        db.commit()
    log.error("analysis failed for %s: %s", return_id, error)


def _save(return_id, run_id, v: dict, fixes, context, tool_results, trace, tokens, model, ms) -> None:
    media_ids = {m["id"] for m in context["media"]}
    findings: dict[str, dict] = {}
    for tr in tool_results:
        if tr["name"] == "analyze_media":
            for f in tr["response"].get("findings", []):
                if f.get("media_id") in media_ids:  # one per media file; later wins
                    findings[f["media_id"]] = f
    with SessionLocal() as db, db.begin():
        db.execute(text("UPDATE return_analysis SET is_current = false WHERE return_id = :r AND is_current"), {"r": return_id})
        aid = db.execute(text("""
            INSERT INTO return_analysis (return_id, agent_run_id, root_cause, reason_mismatch, confidence, explanation,
                evidence, context_notes, recommended_action, needs_manual_review, model_version)
            VALUES (:r, :run, CAST(:rc AS root_cause), :mm, :conf, :expl, CAST(:ev AS jsonb), CAST(:notes AS jsonb),
                CAST(:act AS recommended_action), :manual, :model) RETURNING id"""),
            dict(r=return_id, run=run_id, rc=v["root_cause"], mm=v["reason_mismatch"], conf=v["confidence"],
                 expl=v["explanation"], ev=json.dumps(v["evidence"]), notes=json.dumps(context["context_notes"]),
                 act=v["recommended_action"], manual=v["needs_manual_review"], model=model)).scalar_one()
        for mid, f in findings.items():
            sev = f.get("severity") if f.get("severity") in ("none", "low", "medium", "high") else "none"
            db.execute(text("""INSERT INTO media_finding (analysis_id, return_id, media_id, defect_type, severity,
                                   visible_damage, matches_listing, description)
                               VALUES (:a, :r, :m, :dt, CAST(:sev AS severity_level), :vd, :ml, :d)"""),
                       dict(a=aid, r=return_id, m=mid, dt=f.get("defect_type"), sev=sev,
                            vd=bool(f.get("visible_damage")), ml=f.get("matches_listing"),
                            d=f.get("description") or ""))
        db.execute(text("""UPDATE agent_run SET status = 'succeeded', finished_at = now(), model = :model, tool_calls = CAST(:t AS jsonb),
                           raw_output = CAST(:o AS jsonb), tokens_in = :ti, tokens_out = :to WHERE id = :id"""),
                   dict(id=run_id, model=model, t=json.dumps(trace, default=str),
                        o=json.dumps({"verdict": v, "corrections": fixes, "duration_ms": ms}, default=str),
                        ti=tokens[0], to=tokens[1]))
        db.execute(text("UPDATE returns SET status = 'awaiting_review' WHERE id = :id"), {"id": return_id})
