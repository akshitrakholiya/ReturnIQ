"""Product Intelligence toolset (Flow B). Read-only, parameterized SQL over the tools role.

Shared by the evidence pack builder (code) and the RCA / Q&A agents (drill-downs).
Return rate is by order cohort: orders placed in the window and the returns of those orders.
Causes are final_root_cause when reviewed, else the current AI cause (v_return_effective_cause).
"""
import re

from app.core.config import settings
from app.core.periods import COMPARE_TO, PERIODS, compare_window, window
from app.tools._db import query, query_one

FIXED_GROUPS = ("root_cause", "week", "warehouse", "batch", "reason_mismatch", "media_finding")
FIXED_FILTERS = ("cause", "warehouse", "batch", "reviewed")
_VARIANT_KEY = re.compile(r"^[a-z_]{1,30}$")  # variant dimensions are JSON keys: size, color, model...
NOT_ANALYZED = "not_analyzed"  # no AI cause and no review yet

_BASE = """
  SELECT r.id AS return_id, r.stated_reason::text AS stated, ec.cause::text AS cause,
         COALESCE(ec.is_reviewed, false) AS is_reviewed, r.created_at,
         o.variant, o.batch_id, o.order_date, s.warehouse
  FROM returns r
  JOIN orders o ON o.id = r.order_id
  LEFT JOIN shipment s ON s.order_id = o.id
  LEFT JOIN v_return_effective_cause ec ON ec.return_id = r.id
  WHERE r.product_id = :p AND o.order_date >= :s AND o.order_date < :e"""

_CURRENT_FINDINGS = """
  SELECT mf.return_id, mf.defect_type FROM media_finding mf
  JOIN return_analysis ra ON ra.id = mf.analysis_id AND ra.is_current"""

_GROUP_EXPR = {
    "root_cause": f"COALESCE(b.cause, '{NOT_ANALYZED}')",
    "week": "to_char(date_trunc('week', b.order_date), 'YYYY-MM-DD')",
    "warehouse": "COALESCE(b.warehouse, 'unknown')",
    "batch": "COALESCE(b.batch_id, 'unknown')",
    "reason_mismatch": f"""CASE WHEN b.cause IS NULL THEN '{NOT_ANALYZED}'
                               WHEN b.cause = b.stated THEN 'stated_matches_actual'
                               ELSE 'stated_' || b.stated || '_actual_' || b.cause END""",
    "media_finding": """CASE WHEN f.return_id IS NULL THEN 'no_photo_finding'
                             ELSE COALESCE(f.defect_type, 'no_issue_visible') END""",
}


class ToolInputError(ValueError):
    pass


def _check_period(period: str, compare_to: str | None = None) -> None:
    if period not in PERIODS:
        raise ToolInputError(f"period must be one of {list(PERIODS)}")
    if compare_to is not None and compare_to not in COMPARE_TO:
        raise ToolInputError(f"compare_to must be one of {list(COMPARE_TO)}")


def _where(filter: dict | None, params: dict) -> str:
    """Filter dict -> extra WHERE clauses on the base rows (values always bound as parameters)."""
    sql = []
    for i, (key, value) in enumerate((filter or {}).items()):
        if value in (None, "", False):
            continue
        if key == "cause":
            if value == NOT_ANALYZED:
                sql.append("ec.cause IS NULL")
            else:
                sql.append(f"ec.cause::text = :f{i}")
        elif key == "warehouse":
            sql.append(f"s.warehouse = :f{i}")
        elif key == "batch":
            sql.append(f"o.batch_id = :f{i}")
        elif key == "reviewed":
            sql.append("ec.is_reviewed")
            continue
        elif _VARIANT_KEY.match(key):
            sql.append(f"o.variant ->> :k{i} = :f{i}")
            params[f"k{i}"] = key
        else:
            raise ToolInputError(f"unknown filter '{key}'")
        params[f"f{i}"] = str(value)
    return "".join(f" AND {c}" for c in sql)


def _group_expr(group_by: str, params: dict) -> str:
    if group_by in _GROUP_EXPR:
        return _GROUP_EXPR[group_by]
    if _VARIANT_KEY.match(group_by):  # any variant dimension from the category profile
        params["dim"] = group_by
        return "COALESCE(b.variant ->> :dim, 'unknown')"
    raise ToolInputError(f"group_by must be one of {list(FIXED_GROUPS)} or a variant dimension like size/color/model")


def _counts(product_id: str, group_by: str, filter: dict | None, span) -> tuple[int, dict[str, int]]:
    params = {"p": product_id, "s": span[0], "e": span[1]}
    where = _where(filter, params)
    expr = _group_expr(group_by, params)
    findings = f"LEFT JOIN ({_CURRENT_FINDINGS}) f ON f.return_id = b.return_id" if group_by == "media_finding" else ""
    rows = query(f"""WITH b AS ({_BASE}{where})
                     SELECT {expr} AS grp, count(DISTINCT b.return_id) AS n
                     FROM b {findings} GROUP BY 1""", **params)
    total = query_one(f"SELECT count(*) AS n FROM ({_BASE}{where}) b", **params)["n"]
    return total, {r["grp"]: r["n"] for r in rows}


def return_breakdown(product_id: str, group_by: str, filter: dict | None = None,
                     period: str = "last_90d", compare_to: str = "previous") -> dict:
    """Count returns split by a dimension, with optional filters, and the change vs the compare window.
    filter keys: cause, warehouse, batch, reviewed (true = reviewed only), or any variant dimension."""
    _check_period(period, compare_to)
    filter = {k: v for k, v in (filter or {}).items() if v not in (None, "", False)}
    total, now = _counts(product_id, group_by, filter, window(period))
    prev, cspan = None, compare_window(period, compare_to)
    # week groups never overlap between windows; no orders at all in the compare window = no comparison
    if group_by != "week" and _totals(product_id, cspan)["orders"]:
        _, prev = _counts(product_id, group_by, filter, cspan)
    rows = [{"group": g, "count": n, "share": round(n / total, 3) if total else 0.0,
             "previous_count": prev.get(g, 0) if prev is not None else None,
             "change": n - prev.get(g, 0) if prev is not None else None}
            for g, n in now.items()]
    rows.sort(key=lambda r: (-r["count"], r["group"]))
    if prev is not None:  # groups that disappeared still matter ("defects fell from 5 to 0")
        rows += [{"group": g, "count": 0, "share": 0.0, "previous_count": n, "change": -n}
                 for g, n in sorted(prev.items()) if g not in now]
    return {"product_id": product_id, "group_by": group_by, "filter": filter, "period": period,
            "compare_to": compare_to, "total_returns": total, "rows": rows}


def _rate(orders: int, returns: int) -> float:
    return round(returns / orders, 4) if orders else 0.0


def _totals(product_id: str, span) -> dict:
    t = query_one("""SELECT count(DISTINCT o.id) AS orders, count(DISTINCT r.id) AS returns
                     FROM orders o LEFT JOIN returns r ON r.order_id = o.id
                     WHERE o.product_id = :p AND o.order_date >= :s AND o.order_date < :e""",
                  p=product_id, s=span[0], e=span[1])
    return {**t, "return_rate": _rate(t["orders"], t["returns"])}


def product_history(product_id: str, period: str = "last_90d", compare_to: str = "previous") -> dict:
    """Orders, returns, return rate, weekly trend and change vs the compare window."""
    _check_period(period, compare_to)
    span, prev_span = window(period), compare_window(period, compare_to)
    now, prev = _totals(product_id, span), _totals(product_id, prev_span)
    previous_rate = prev["return_rate"] if prev["orders"] else None
    trend = "flat"
    if previous_rate is not None and previous_rate > 0:
        ratio = now["return_rate"] / previous_rate
        trend = ("rising" if ratio >= 1 + settings.trend_change_ratio
                 else "falling" if ratio <= 1 - settings.trend_change_ratio else "flat")
    elif previous_rate == 0 and now["returns"] > 0:
        trend = "rising"
    weekly = query("""SELECT to_char(date_trunc('week', o.order_date), 'YYYY-MM-DD') AS week,
                             count(DISTINCT o.id) AS orders, count(DISTINCT r.id) AS returns
                      FROM orders o LEFT JOIN returns r ON r.order_id = o.id
                      WHERE o.product_id = :p AND o.order_date >= :s AND o.order_date < :e
                      GROUP BY 1 ORDER BY 1""", p=product_id, s=span[0], e=span[1])
    return {"product_id": product_id, "period": period, "compare_to": compare_to,
            "window": {"start": span[0].isoformat(), "end": span[1].isoformat()},
            **now, "previous": prev | {"return_rate": previous_rate}, "trend": trend, "weekly": weekly}


def category_baseline(category: str, period: str = "last_90d") -> dict:
    """Category-wide return rate in the period, plus the rate for each cause (for the ₹ impact)."""
    _check_period(period)
    s, e = window(period)
    t = query_one("""SELECT count(DISTINCT o.id) AS orders, count(DISTINCT r.id) AS returns
                     FROM orders o JOIN product p ON p.id = o.product_id
                     LEFT JOIN returns r ON r.order_id = o.id
                     WHERE p.category = :c AND o.order_date >= :s AND o.order_date < :e""", c=category, s=s, e=e)
    causes = query("""SELECT ec.cause::text AS cause, count(*) AS n
                      FROM returns r JOIN orders o ON o.id = r.order_id JOIN product p ON p.id = r.product_id
                      JOIN v_return_effective_cause ec ON ec.return_id = r.id
                      WHERE p.category = :c AND o.order_date >= :s AND o.order_date < :e AND ec.cause IS NOT NULL
                      GROUP BY 1""", c=category, s=s, e=e)
    return {"category": category, "period": period, **t, "return_rate": _rate(t["orders"], t["returns"]),
            "cause_rates": {c["cause"]: _rate(t["orders"], c["n"]) for c in causes}}


def return_feedback(product_id: str, filter: dict | None = None, period: str = "last_90d", limit: int = 15) -> dict:
    """Stated reasons, comments, reviewer notes and stored photo findings, reviewed returns first."""
    _check_period(period)
    s, e = window(period)
    params = {"p": product_id, "s": s, "e": e, "limit": max(1, min(int(limit), 30))}
    where = _where(filter, params)
    rows = query(f"""
        SELECT r.id AS return_id, ec.cause::text AS cause, COALESCE(ec.is_reviewed, false) AS reviewed,
               r.stated_reason::text AS stated_reason, r.comment, rv.note AS reviewer_note,
               (SELECT string_agg(COALESCE(mf.defect_type, 'no visible issue') || ', ' || mf.severity, '; ')
                  FROM media_finding mf JOIN return_analysis ra ON ra.id = mf.analysis_id AND ra.is_current
                 WHERE mf.return_id = r.id) AS media_finding,
               o.variant, o.batch_id, s.warehouse
        FROM returns r
        JOIN orders o ON o.id = r.order_id
        LEFT JOIN shipment s ON s.order_id = o.id
        LEFT JOIN v_return_effective_cause ec ON ec.return_id = r.id
        LEFT JOIN return_review rv ON rv.return_id = r.id
        WHERE r.product_id = :p AND o.order_date >= :s AND o.order_date < :e{where}
        ORDER BY COALESCE(ec.is_reviewed, false) DESC, r.created_at DESC, r.id
        LIMIT :limit""", **params)
    return {"product_id": product_id, "filter": filter or {}, "period": period, "items": rows}


# ───────────── agent-facing wrappers ─────────────
# Explicit optional parameters instead of a free-form dict: Gemini fills simple typed arguments
# more reliably, and the docstrings tell it when to use each tool.

def _filter(cause="", size="", color="", model="", warehouse="", batch="", reviewed_only=False) -> dict:
    f = {"cause": cause, "size": size, "color": color, "model": model,
         "warehouse": warehouse, "batch": batch, "reviewed": reviewed_only}
    return {k: v for k, v in f.items() if v not in ("", None, False)}


def get_return_breakdown(product_id: str, group_by: str, cause: str = "", size: str = "", color: str = "",
                         model: str = "", warehouse: str = "", batch: str = "", reviewed_only: bool = False,
                         period: str = "last_90d", compare_to: str = "previous") -> dict:
    """Count this product's returns split by any dimension, with optional filters, and the change
    vs the previous period. Use it to drill into a hypothesis the evidence pack does not answer,
    e.g. group_by="warehouse" with cause="damaged_in_transit", or group_by="batch" with size="L".
    group_by: root_cause | size | color | model | week | warehouse | batch | reason_mismatch | media_finding.
    Filters are optional; leave empty to not filter. cause is a root cause like size_fit.
    period: this_month | last_month | last_30d | last_90d. compare_to: previous | last_month | last_90d."""
    return return_breakdown(product_id, group_by, _filter(cause, size, color, model, warehouse, batch, reviewed_only),
                            period, compare_to)


def get_return_feedback(product_id: str, cause: str = "", size: str = "", color: str = "", model: str = "",
                        warehouse: str = "", batch: str = "", reviewed_only: bool = False,
                        period: str = "last_90d", limit: int = 10) -> dict:
    """Read what customers and reviewers said about this product's returns: stated reason, comment,
    reviewer note and the stored photo finding, reviewed returns first. Filters are optional.
    Use it to check whether comments support a hypothesis. Cite items by return_id (like 'r_101')."""
    return return_feedback(product_id, _filter(cause, size, color, model, warehouse, batch, reviewed_only),
                           period, limit)


def get_product_history(product_id: str, period: str = "last_90d", compare_to: str = "previous") -> dict:
    """Get this product's orders, returns, return rate and weekly trend for a period, with the
    previous period for comparison. period: this_month | last_month | last_30d | last_90d."""
    return product_history(product_id, period, compare_to)
