"""Flow A context builder: plain code, no AI.

Calls the same tool functions the agent uses, so each data function is written once.
Records what is missing as completeness notes so the agent never concludes about it.
"""
from app.services.storage import MAX_LISTING_IMAGES, load_bytes
from app.tools.order_shipment import (get_customer_return_history, get_order_details, get_return,
                                      get_shipment)
from app.tools.product_catalog import get_category_profile, get_product_listing


class ContextError(Exception):
    pass


def build_return_context(return_id: str) -> dict:
    ret = get_return(return_id)
    if not ret["found"]:
        raise ContextError(ret["error"])
    order = get_order_details(ret["order_id"])
    shipment = get_shipment(ret["order_id"])
    history = get_customer_return_history(ret["customer_id"])
    listing = get_product_listing(ret["product_id"])
    if not order["found"] or not listing["found"]:
        raise ContextError(f"incomplete data for {return_id}: order/listing missing")
    profile = get_category_profile(listing["category"])

    notes: list[str] = []
    if not ret["media"]:
        notes.append("No media provided; cannot judge the product's condition from photos.")
    if not shipment["found"]:
        notes.append("No shipment record; cannot conclude anything about delivery or transit damage.")
    elif shipment["delivered_date"] is None:
        notes.append("Shipment has no delivered date.")
    if not listing["listing_image_urls"]:
        notes.append("Listing has no images; cannot compare the customer's photos with the listing.")
    elif not any(load_bytes(u) for u in listing["listing_image_urls"][:MAX_LISTING_IMAGES]):
        notes.append("Listing images could not be loaded; cannot judge whether the item matches the listing.")
    if not profile["found"]:
        notes.append(f"No category profile for '{listing['category']}'; using generic checks.")
    else:
        for attr in profile["key_attributes"]:
            if attr not in listing["attributes"]:
                notes.append(f"Listing has no {attr}; cannot conclude anything about {attr}.")

    # IDs the agent may cite as evidence (used later by the citation check).
    known_refs = [ret["id"], order["id"], listing["id"], *[m["id"] for m in ret["media"]],
                  *[r["id"] for r in history["recent_returns"]]]
    if shipment["found"]:
        known_refs.append(shipment["id"])

    ret_view = {k: v for k, v in ret.items() if k not in ("found", "media")}
    return {
        "return": ret_view,
        "media": ret["media"],
        "order": {k: v for k, v in order.items() if k != "found"},
        "shipment": {k: v for k, v in shipment.items() if k != "found"} if shipment["found"] else None,
        "customer_history": history,
        "listing": {k: v for k, v in listing.items() if k != "found"},
        "category_profile": {k: v for k, v in profile.items() if k != "found"} if profile["found"] else None,
        "context_notes": notes,
        "known_refs": known_refs,
    }
