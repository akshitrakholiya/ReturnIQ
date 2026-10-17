"""Product Catalog toolset (Flow A). Read-only."""
from app.tools._db import query_one


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
