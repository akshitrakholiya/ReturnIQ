"""Seed deterministic Flow B reference data after the base dataset exists."""
import json

from sqlalchemy import create_engine, text

from app.core.config import settings


COSTS = {
    "apparel": (90, 30, 0.25, 250),
    "footwear": (120, 40, 0.30, 400),
    "electronics_accessories": (70, 25, 0.20, 180),
}


def seed_flow_b() -> None:
    engine = create_engine(settings.app_url)
    with engine.begin() as db:
        db.execute(text("""
            INSERT INTO cost_model (category, reverse_shipping, restocking, write_off_rate, margin)
            VALUES (:category, :reverse_shipping, :restocking, :write_off_rate, :margin)
            ON CONFLICT (category) DO UPDATE SET
              reverse_shipping = EXCLUDED.reverse_shipping,
              restocking = EXCLUDED.restocking,
              write_off_rate = EXCLUDED.write_off_rate,
              margin = EXCLUDED.margin
        """), [
            dict(category=category, reverse_shipping=shipping, restocking=restocking,
                 write_off_rate=write_off, margin=margin)
            for category, (shipping, restocking, write_off, margin) in COSTS.items()
        ])

        # Listing history is deliberately sparse: it is evidence when a product has
        # a recent change, not a synthetic change for every product.
        products = db.execute(text("SELECT id, category FROM product ORDER BY id LIMIT 4")).mappings().all()
        rows = []
        for product in products:
            if product["category"] == "apparel":
                rows.append(dict(product_id=product["id"], field="attributes.size_chart",
                                 old_value=json.dumps({"M": {"chest_cm": 102}}),
                                 new_value=json.dumps({"M": {"chest_cm": 98}})))
            elif product["category"] == "footwear":
                rows.append(dict(product_id=product["id"], field="description",
                                 old_value="rubber sole", new_value="reinforced rubber sole"))
            else:
                rows.append(dict(product_id=product["id"], field="attributes.compatible_models",
                                 old_value=json.dumps(["Pixel 8"]), new_value=json.dumps(["Pixel 8", "Pixel 9"])))
        if rows:
            db.execute(text("""
                INSERT INTO listing_change (product_id, field, old_value, new_value)
                SELECT :product_id, :field, :old_value, :new_value
                WHERE NOT EXISTS (
                  SELECT 1 FROM listing_change
                  WHERE product_id = :product_id AND field = :field
                )
            """), rows)
        print(f"seeded Flow B: {len(COSTS)} cost models, {len(rows)} listing changes")


if __name__ == "__main__":
    seed_flow_b()
