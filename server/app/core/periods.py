"""Report windows for Flow B. Return rate is by order cohort: orders placed in the window and
the returns of those orders. Every window ends at settings.as_of (REPORT_AS_OF or now)."""
from datetime import datetime, timedelta

from app.core.config import settings

PERIODS = ("this_month", "last_month", "last_30d", "last_90d")
COMPARE_TO = ("previous", "last_month", "last_90d")
LABELS = {"this_month": "this month", "last_month": "last month", "last_30d": "last 30 days",
          "last_90d": "last 90 days"}


def _month_start(d: datetime) -> datetime:
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def window(period: str, as_of: datetime | None = None) -> tuple[datetime, datetime]:
    """[start, end) of a period."""
    end = as_of or settings.as_of
    if period == "last_90d":
        return end - timedelta(days=90), end
    if period == "last_30d":
        return end - timedelta(days=30), end
    if period == "this_month":
        return _month_start(end), end
    if period == "last_month":
        this = _month_start(end)
        return _month_start(this - timedelta(days=1)), this
    raise ValueError(f"period must be one of {PERIODS}")


def compare_window(period: str, compare_to: str, as_of: datetime | None = None) -> tuple[datetime, datetime]:
    """The window a period is compared with. 'previous' = the same length right before it."""
    if compare_to == "previous":
        start, end = window(period, as_of)
        if period == "this_month":
            return window("last_month", as_of)
        if period == "last_month":
            return _month_start(start - timedelta(days=1)), start
        return start - (end - start), start
    if compare_to in ("last_month", "last_90d"):
        return window(compare_to, as_of)
    raise ValueError(f"compare_to must be one of {COMPARE_TO}")


def days(span: tuple[datetime, datetime]) -> float:
    return max((span[1] - span[0]).total_seconds() / 86400, 1.0)
