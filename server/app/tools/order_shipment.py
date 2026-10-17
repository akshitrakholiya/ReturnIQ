"""Order & Shipment toolset (Flow A). Read-only; none of these return customer PII."""
from app.tools._db import query, query_one


def get_return(return_id: str) -> dict:
    """Get a customer's return request: stated reason, comment, order, product, customer and
    the list of uploaded media (id, type, storage_url). Use the return_id like 'r_101'."""
    r = query_one("""SELECT id, order_id, product_id, customer_id, stated_reason, comment, status, created_at
                     FROM returns WHERE id = :id""", id=return_id)
    if not r:
        return {"found": False, "error": f"return {return_id} not found"}
    media = query("SELECT id, type, storage_url FROM return_media WHERE return_id = :id ORDER BY id", id=return_id)
    return {"found": True, **r, "media": media}


def get_order_details(order_id: str) -> dict:
    """Get what was ordered: variant (size/color/model), batch_id, price and order date.
    Use the order_id like 'o_456'."""
    o = query_one("""SELECT id, product_id, customer_id, variant, batch_id, price, order_date
                     FROM orders WHERE id = :id""", id=order_id)
    return {"found": True, **o} if o else {"found": False, "error": f"order {order_id} not found"}


def get_shipment(order_id: str) -> dict:
    """Get delivery details for an order: dispatch warehouse, shipped and delivered dates, and
    damage_flag (logistics' own record of damage on delivery, not the customer's claim)."""
    s = query_one("""SELECT id, order_id, warehouse, shipped_at, delivered_date, damage_flag
                     FROM shipment WHERE order_id = :id""", id=order_id)
    return {"found": True, **s} if s else {"found": False, "error": f"no shipment record for order {order_id}"}


def get_customer_return_history(customer_id: str) -> dict:
    """Count a customer's total orders and total returns, and list their 5 most recent returns
    (id, stated_reason, date). Use it to spot repeated-return patterns."""
    totals = query_one("""SELECT (SELECT count(*) FROM orders  WHERE customer_id = :c) AS total_orders,
                                 (SELECT count(*) FROM returns WHERE customer_id = :c) AS total_returns""", c=customer_id)
    recent = query("""SELECT id, stated_reason, created_at FROM returns
                      WHERE customer_id = :c ORDER BY created_at DESC LIMIT 5""", c=customer_id)
    return {"customer_id": customer_id, **totals, "recent_returns": recent}
