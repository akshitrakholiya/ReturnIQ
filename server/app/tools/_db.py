"""Shared helper for the tool layer: parameterized SQL over the read-only role only."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.db.session import tools_engine


def _json_safe(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    return v


def query(sql: str, **params) -> list[dict]:
    """Run a parameterized SELECT as returniq_tools (read-only, 60 s statement timeout)."""
    with tools_engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [_json_safe(dict(r)) for r in rows]


def query_one(sql: str, **params) -> dict | None:
    rows = query(sql, **params)
    return rows[0] if rows else None
