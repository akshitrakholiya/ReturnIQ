"""Flow B step 6 (code): checks and scoring. Turns the agents' findings and fixes into the ProductReport.

Gemini never sets a number here: supporting counts are verified against the pack, and confidence,
₹ impact and rank are computed from SQL numbers (rules in the HLD/LLD's last section).
"""
from app.core.config import settings
from app.core.periods import LABELS, days, window
from app.schemas.flow_b import (Affected, CheckReport, Confidence, CostModel, EvidencePack, Impact, ProductReport,
                                RCAFindings, RejectedHypothesis, ReportRootCause, SolutionOutput, ToolResult)
from app.services.flow_b import checks
from app.tools.product_intelligence import NOT_ANALYZED, category_baseline, return_breakdown

MODEL_VERSION = "returniq-flowb-0.1"


def _rows(pack: EvidencePack, id_: str) -> list:
    b = next((b for b in pack.breakdowns if b.id == id_), None)
    return b.rows if b else []


def _source_types(refs: list[str], tool_results: list[ToolResult]) -> set[str]:
    """Which kinds of source agree: numbers, comments/notes, photo findings, listing check."""
    media_tools = {t.ref_id for t in tool_results if t.args.get("group_by") == "media_finding"}
    types = set()
    for r in refs:
        if r == "breakdown:media" or r in media_tools:
            types.add("photo")
        elif r.startswith(("breakdown:", "tool:")) or r == "metrics":
            types.add("numbers")
        elif r.startswith("r_"):
            types.add("comments")
        elif r in ("listing", "profile") or r.startswith("lc_"):
            types.add("listing")
    return types


def photo_share(pack: EvidencePack, cause: str) -> float | None:
    """Of this cause's returns that have photo findings, the share showing an issue."""
    b = next((b for b in pack.breakdowns if b.id == "breakdown:media" and b.filter.get("cause") == cause), None)
    rows = [r.model_dump() for r in b.rows] if b else \
        return_breakdown(pack.product_id, "media_finding", {"cause": cause}, pack.period, pack.compare_to)["rows"]
    with_photo = sum(r["count"] for r in rows if r["group"] != "no_photo_finding")
    clear = sum(r["count"] for r in rows if r["group"] == "no_issue_visible")
    return (with_photo - clear) / with_photo if with_photo else None


def confidence(share: float, supporting: int, refs: list[str], counter: int, photo: float | None,
               tool_results: list[ToolResult]) -> Confidence:
    parts = {"share": round(30 * min(share, 1.0)),
             "volume": min(supporting, 20),
             "agreement": round(30 * len(_source_types(refs, tool_results)) / 4),
             "photo": round(20 * photo) if photo is not None else 0,
             "contradiction": -round(25 * counter / (len(refs) + counter)) if counter else 0}
    score = max(0, min(100, sum(parts.values())))
    return Confidence(score=score, level="high" if score >= 75 else "medium" if score >= 50 else "low", breakdown=parts)


def cost_per_return(cost: CostModel | None) -> float:
    return round(cost.reverse_shipping + cost.restocking + cost.write_off_rate * cost.margin, 2) if cost else 0.0


def impact(pack: EvidencePack, cause: str, cause_count: int, supporting: int, cause_rate: float,
           cost: CostModel | None) -> Impact:
    """Extra returns = this cause's returns above the category-rate expectation for the same orders, per month."""
    expected = pack.metrics.orders * cause_rate
    excess = max(0.0, 1 - expected / cause_count) if cause_count else 0.0
    per_month = round(supporting * excess * 30 / days(window(pack.period)))
    per_return = cost_per_return(cost)
    return Impact(extra_returns_per_month=per_month, cost_per_return_inr=per_return,
                  monthly_cost_inr=round(per_month * per_return, 2))


def mismatch_share(pack: EvidencePack) -> float | None:
    rows = _rows(pack, "breakdown:mismatch")
    analyzed = sum(r.count for r in rows if r.group != NOT_ANALYZED)
    mismatched = sum(r.count for r in rows if r.group not in (NOT_ANALYZED, "stated_matches_actual"))
    return round(mismatched / analyzed, 3) if analyzed else None


def build_report(pack: EvidencePack, findings: RCAFindings | None, solution: SolutionOutput | None,
                 cost: CostModel | None, tool_results: list[ToolResult], retried: bool,
                 model_version: str | None, extra_notes: list[str] = ()) -> ProductReport:
    report = CheckReport(retried_agent=retried)
    notes = list(pack.completeness_notes) + list(extra_notes)
    if cost is None:
        notes.append(f"No cost model for '{pack.listing.category}'; ₹ impact shown as 0")
    if findings is None:
        return ProductReport(product_id=pack.product_id, evidence_pack_id=pack.pack_id, status="analyzed",
                             period=pack.period, summary="Analysis unavailable: the root-cause step failed. Retry later.",
                             metrics=pack.metrics, reason_mismatch_share=mismatch_share(pack),
                             data_notes=notes, checks=report, model_version=model_version)

    refs = checks.known_refs(pack, tool_results)
    allowed = checks.evidence_numbers(pack, tool_results)
    counts = {r.group: r.count for r in _rows(pack, "breakdown:root_cause")}
    total = pack.metrics.returns
    rates = category_baseline(pack.listing.category, pack.period)["cause_rates"]
    fixes = {f.cause_id: f for f in (solution.fixes if solution else [])}

    causes: list[ReportRootCause] = []
    for rc in findings.root_causes:
        evidence, dropped = checks.keep_cited(rc.evidence, refs)
        counter, dropped_c = checks.keep_cited(rc.counter_evidence, refs)
        report.dropped_evidence += [f"{rc.cause_id}:{r}" for r in dropped + dropped_c]
        evidence, bad = checks.keep_numbers(evidence, allowed)
        counter, bad_c = checks.keep_numbers(counter, allowed)
        title, bad_t = checks.strip_sentences(rc.title, allowed)
        if bad + bad_c + bad_t:
            report.number_mismatches += [f"{rc.cause_id}: {n}" for n in sorted(set(bad + bad_c + bad_t))]

        count = counts.get(rc.cause.value, 0)
        # the agent's count is used only when it is a number from the evidence and within the cause's total
        supporting = rc.supporting_returns if (checks.canon(rc.supporting_returns) in allowed
                                               and 0 < rc.supporting_returns <= count) else count
        share = supporting / total if total else 0.0
        if supporting < settings.rca_min_returns or share < settings.rca_min_share:
            report.dropped_causes.append(f"{rc.cause_id} ({rc.cause.value}): {supporting} supporting returns, "
                                         f"{share:.0%} share; below the evidence bar")
            continue
        if len(evidence) < 2:
            report.dropped_causes.append(f"{rc.cause_id} ({rc.cause.value}): fewer than 2 verified evidence items")
            continue

        fix = fixes.get(rc.cause_id)
        fix_text = None
        if rc.owner != "none" and fix:
            if checks.numbers_in(fix.fix) <= allowed:
                fix_text = fix.fix
            else:
                report.number_mismatches.append(f"{rc.cause_id} fix: {sorted(checks.numbers_in(fix.fix) - allowed)}")
        causes.append(ReportRootCause(
            cause_id=rc.cause_id, title=title or rc.cause.value.replace("_", " "), cause=rc.cause, owner=rc.owner,
            evidence=evidence, counter_evidence=counter, affected=rc.affected or Affected(), fix=fix_text,
            confidence=confidence(share, supporting, [e.ref for e in evidence], len(counter),
                                  photo_share(pack, rc.cause.value), tool_results),
            impact=impact(pack, rc.cause.value, count, supporting, rates.get(rc.cause.value, 0.0), cost), rank=0))

    causes.sort(key=lambda c: (-c.impact.monthly_cost_inr, -c.confidence.score))
    for i, c in enumerate(causes, 1):
        c.rank = i

    rejected = []
    for h in findings.rejected_hypotheses:
        if checks.numbers_in(h.reason) <= allowed:
            rejected.append(RejectedHypothesis(hypothesis=h.hypothesis, reason=h.reason, refs=[r for r in h.refs if r in refs]))
        else:
            report.number_mismatches.append(f"rejected '{h.hypothesis}': {sorted(checks.numbers_in(h.reason) - allowed)}")

    summary, bad_s = checks.strip_sentences(findings.summary, allowed)
    if bad_s:
        report.number_mismatches.append(f"summary: {bad_s}")
    if findings.root_causes and not causes:
        summary = ("No root cause met the evidence bar (at least "
                   f"{settings.rca_min_returns} returns and {settings.rca_min_share:.0%} of returns); see rejected hypotheses.")
    for n in findings.data_notes:
        if n not in notes and checks.numbers_in(n) <= allowed:
            notes.append(n)
    return ProductReport(product_id=pack.product_id, evidence_pack_id=pack.pack_id, status="analyzed",
                         period=pack.period, summary=summary or "Returns analyzed; see root causes below.",
                         metrics=pack.metrics, root_causes=causes, rejected_hypotheses=rejected,
                         reason_mismatch_share=mismatch_share(pack), data_notes=notes, checks=report,
                         model_version=model_version or MODEL_VERSION)


def short_report(product_id: str, decision: str, health, period: str) -> ProductReport:
    """not_enough_data / healthy: no agents, numbers straight from the health check."""
    m = health.metrics
    label = LABELS.get(period, period)
    if decision == "not_enough_data":
        summary = f"Only {m.returns} returns in the {label}, not enough to find a pattern."
    else:
        summary = (f"Looks healthy: return rate {m.return_rate:.1%} vs category {m.category_rate:.1%}"
                   f"{', not rising' if m.trend != 'rising' else ''}.")
    return ProductReport(product_id=product_id, status=decision, period=period, summary=summary, metrics=m,
                         top_reasons=health.top_reasons)
