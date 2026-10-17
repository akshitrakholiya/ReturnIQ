"""Flow B step 3 (code): build and save the evidence pack.

Calls the same tool functions the agents use, tags every item with a citable ID, and records what
is missing as completeness notes so the agents never conclude about it.

Breakdowns: root_cause, mismatch and week cover all returns. The splits (each profile variant
dimension, warehouse, batch, photo findings) are filtered to the top cause, where a concentration
means something; agents drill down with get_return_breakdown for anything else.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.flow_b import (Breakdown, BreakdownRow, CategoryProfile, EvidencePack, EvidencePackInput,
                                FeedbackItem, ListingChange, ListingInfo, ProductMetrics)
from app.tools.product_catalog import get_category_profile, get_listing_changes, get_product_listing
from app.tools.product_intelligence import NOT_ANALYZED, return_breakdown, return_feedback

PACK_FIELDS = ("product_id", "period", "compare_to", "metrics", "breakdowns", "feedback", "listing",
               "listing_changes", "profile", "completeness_notes")


class PackError(Exception):
    pass


def _breakdown(id_: str, raw: dict) -> Breakdown:
    return Breakdown(id=id_, group_by=raw["group_by"], filter=raw["filter"],
                     rows=[BreakdownRow(**{k: r[k] for k in ("group", "count", "share", "previous_count", "change")})
                           for r in raw["rows"]])


def _analyzed(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["group"] != NOT_ANALYZED and r["count"] > 0]


def build_evidence_pack(db: Session, inp: EvidencePackInput, metrics: ProductMetrics,
                        root_cause: dict | None = None) -> EvidencePack:
    """Gather (tools) -> notes -> save. root_cause: the health check's breakdown, reused if given."""
    listing = get_product_listing(inp.product_id)
    if not listing["found"]:
        raise PackError(listing["error"])
    profile = get_category_profile(inp.category)
    dims = profile["variant_dimensions"] if profile["found"] else []

    args = dict(period=inp.period, compare_to=inp.compare_to)
    causes = root_cause or return_breakdown(inp.product_id, "root_cause", **args)
    ranked = _analyzed(causes["rows"])
    top = ranked[0]["group"] if ranked else None
    focus = {"cause": top} if top else {}

    breakdowns = [_breakdown("breakdown:root_cause", causes),
                  _breakdown("breakdown:mismatch", return_breakdown(inp.product_id, "reason_mismatch", **args))]
    for dim in dims:
        breakdowns.append(_breakdown(f"breakdown:{dim}", return_breakdown(inp.product_id, dim, focus, **args)))
    breakdowns.append(_breakdown("breakdown:week", return_breakdown(inp.product_id, "week", **args)))
    for group_by in ("warehouse", "batch"):
        breakdowns.append(_breakdown(f"breakdown:{group_by}", return_breakdown(inp.product_id, group_by, focus, **args)))
    media = return_breakdown(inp.product_id, "media_finding", focus, **args)
    breakdowns.append(_breakdown("breakdown:media", media))

    feedback: list[FeedbackItem] = []
    for r in ranked[:2]:  # comments and notes for the top 2 causes
        for item in return_feedback(inp.product_id, {"cause": r["group"]}, inp.period, settings.feedback_per_cause)["items"]:
            feedback.append(FeedbackItem(
                return_id=item["return_id"], cause=item["cause"], reviewed=item["reviewed"],
                stated_reason=item["stated_reason"], comment=item["comment"], reviewer_note=item["reviewer_note"],
                media_finding=item["media_finding"],
                variant={k: str(v) for k, v in (item["variant"] or {}).items()}))

    changes = [ListingChange(id=c["id"], field=c["field"], old_value=c["old_value"], new_value=c["new_value"],
                             changed_at=c["changed_at"])
               for c in get_listing_changes(inp.product_id, inp.period)["changes"]]
    listing_info = ListingInfo(title=listing["name"], category=listing["category"],
                               description=listing["description"] or "", attributes=listing["attributes"] or {},
                               listing_image_urls=listing["listing_image_urls"] or [])
    profile_info = (CategoryProfile(**{k: profile[k] for k in ("category", "variant_dimensions", "key_attributes",
                                                                "media_focus", "listing_checks")})
                    if profile["found"] else
                    CategoryProfile(category=inp.category, variant_dimensions=[], key_attributes=[],
                                    media_focus="", listing_checks=[]))

    notes = completeness_notes(inp, metrics, causes, media if not top else None, listing, profile)
    items = dict(product_id=inp.product_id, period=inp.period, compare_to=inp.compare_to, metrics=metrics,
                 breakdowns=breakdowns, feedback=feedback, listing=listing_info, listing_changes=changes,
                 profile=profile_info, completeness_notes=notes)
    payload = EvidencePack(pack_id="", created_at=datetime.now(timezone.utc), **items).model_dump(
        mode="json", include=set(PACK_FIELDS))
    row = db.execute(text("""INSERT INTO evidence_pack (product_id, period, items, completeness_notes)
                             VALUES (:p, :period, CAST(:items AS jsonb), CAST(:notes AS jsonb))
                             RETURNING id, created_at"""),
                     dict(p=inp.product_id, period=inp.period, items=json.dumps(payload), notes=json.dumps(notes))).one()
    db.commit()
    return EvidencePack(pack_id=row.id, created_at=row.created_at, **items)


def completeness_notes(inp: EvidencePackInput, metrics: ProductMetrics, causes: dict, media_all: dict | None,
                       listing: dict, profile: dict) -> list[str]:
    total = causes["total_returns"]
    notes: list[str] = []
    reviewed = return_breakdown(inp.product_id, "root_cause", {"reviewed": True}, inp.period, inp.compare_to)["total_returns"]
    if total and reviewed < total:
        notes.append(f"{total - reviewed} of {total} returns not yet reviewed")
        if reviewed / total < 0.5:
            notes.append("Under half of the returns are reviewed; treat causes as provisional")
    not_analyzed = next((r["count"] for r in causes["rows"] if r["group"] == NOT_ANALYZED), 0)
    if not_analyzed:
        notes.append(f"{not_analyzed} returns have no AI cause or review yet; they count in totals but not in cause splits")
    media_all = media_all or return_breakdown(inp.product_id, "media_finding", period=inp.period, compare_to=inp.compare_to)
    no_photo = next((r["count"] for r in media_all["rows"] if r["group"] == "no_photo_finding"), 0)
    if no_photo:
        notes.append(f"{no_photo} of {total} returns have no photo findings")
    if metrics.previous_return_rate is None:
        notes.append("No orders in the previous period; trend and change vs previous are not available")
    if not listing["listing_image_urls"]:
        notes.append("Listing has no images; do not conclude anything about listing photos")
    if not profile["found"]:
        notes.append(f"No category profile for '{inp.category}'; using generic checks")
    else:
        for attr in profile["key_attributes"]:
            if attr not in (listing["attributes"] or {}):
                notes.append(f"Listing has no {attr}; do not conclude anything about {attr}")
    return notes


def load_pack(db: Session, pack_id: str) -> EvidencePack:
    row = db.execute(text("SELECT id, items, created_at FROM evidence_pack WHERE id = :id"), {"id": pack_id}).one()
    return EvidencePack(pack_id=row.id, created_at=row.created_at, **{k: row.items[k] for k in PACK_FIELDS})


def pack_refs(pack: EvidencePack) -> set[str]:
    """Every ID an agent may cite from the pack."""
    return ({"metrics", "listing", "profile"} | {b.id for b in pack.breakdowns}
            | {f.return_id for f in pack.feedback} | {c.id for c in pack.listing_changes})
