"""Dev-only helpers for the test front end. Not part of the design's 13 endpoints; remove before production."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_session

router = APIRouter(prefix="/demo", tags=["demo (dev only)"])
DB = Annotated[Session, Depends(get_session)]


@router.get("/products")
def demo_products(db: DB):
    """Products with how many orders can still be returned (no PII)."""
    rows = db.execute(text("""
        SELECT p.id, p.name, p.category,
               count(o.id) FILTER (WHERE r.id IS NULL) AS returnable_orders
        FROM product p LEFT JOIN orders o ON o.product_id = p.id LEFT JOIN returns r ON r.order_id = o.id
        GROUP BY p.id ORDER BY p.name""")).mappings().all()
    return [dict(r) for r in rows]


@router.get("/orders")
def demo_orders(db: DB, product_id: str, limit: int = Query(15, le=50)):
    """Recent orders of a product that have no return yet."""
    rows = db.execute(text("""
        SELECT o.id, o.variant, o.batch_id, o.price, o.order_date, s.warehouse, s.delivered_date
        FROM orders o LEFT JOIN returns r ON r.order_id = o.id LEFT JOIN shipment s ON s.order_id = o.id
        WHERE o.product_id = :p AND r.id IS NULL ORDER BY o.order_date DESC LIMIT :l"""),
        {"p": product_id, "l": limit}).mappings().all()
    return [dict(r) for r in rows]
