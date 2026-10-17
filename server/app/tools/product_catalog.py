"""Product Catalog toolset (Flow A + B). Read-only."""
import json

from app.core.periods import window
from app.tools._db import query, query_one


def get_product_listing(product_id: str) -> dict:
    """Get a product's listing: name, category, description, attributes (size chart / specs /
    dimensions) and listing image URLs. Use the product_id like 'p_12'."""
    p = query_one("""SELECT id, name, category, description, attributes, listing_image_urls
                     FROM product WHERE id = :id""", id=product_id)
    return {"found": True, **p} if p else {"found": False, "error": f"product {product_id} not found"}


def get_category_profile(category: str) -> dict:
    """Get what to check for a product category: variant_dimensions, key_attributes, media_focus
    (what to look for in photos) and listing_checks. Example category: 'apparel'."""
    c = query_one("""SELECT category, variant_dimensions, key_attributes, media_focus, listing_checks
                     FROM category_profile WHERE category = :c""", c=category)
    return {"found": True, **c} if c else {"found": False, "error": f"no profile for category {category}"}


def _maybe_json(v):
    try:
        return json.loads(v) if isinstance(v, str) else v
    except ValueError:
        return v


def get_listing_changes(product_id: str, period: str = "last_90d") -> dict:
    """List changes made to a product's listing in a period (field, old value, new value, changed_at),
    newest first. Use it to check whether returns rose after a size chart, photo or description change.
    period: this_month | last_month | last_30d | last_90d. Cite each change by its id (like 'lc_3')."""
    start, end = window(period)
    rows = query("""SELECT id, field, old_value, new_value, changed_at FROM listing_change
                    WHERE product_id = :p AND changed_at >= :s AND changed_at < :e
                    ORDER BY changed_at DESC""", p=product_id, s=start, e=end)
    return {"product_id": product_id, "period": period,
            "changes": [r | {"old_value": _maybe_json(r["old_value"]), "new_value": _maybe_json(r["new_value"])}
                        for r in rows]}
