"""Add SYNTHETIC related data for the footwear and electronics_accessories categories.

    python -m scripts.add_category_data            # add 6 products (FW01-03, EL01-03) with orders, shipments, returns
    python -m scripts.add_category_data --remove   # delete exactly what this script added

The dataset only covers apparel. This gives the other two category profiles something to run on:
  - ids are prefixed FW.. / EL.. (products), ORD-2xxx / SHP-2xxx, so they never mix with dataset rows
  - every new return is 'pending_analysis' (nothing reviewed), for the Return Agent to analyze
  - about 1 in 4 returns has a stated reason that differs from the true cause (the dataset has none);
    the comment describes the real symptom. True causes go to eval_label (scenario 'synthetic_category_data')
  - listing images: none (the agent gets the "listing has no images" note)
  - return photos: only where a genuine sample photo fits (sample_images/): worn shoes for footwear
    defect returns and a crushed parcel for transit damage. All other returns have no media.
"""
import argparse
import json
import random
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

from app.core.config import settings
from app.services.storage import storage
from scripts.seed import alloc, insert

REPO_ROOT = Path(__file__).resolve().parent.parent.parent   # sample_images/ lives at the repo root
SAMPLES = REPO_ROOT / "sample_images"
PRODUCT_PREFIXES = ("FW", "EL")
WAREHOUSES = ["Pune", "Delhi", "Bengaluru"]
BATCHES = ["B31", "B34", "B36", "B40", "B42"]
ORDER_START, ORDER_END = datetime(2026, 7, 29), datetime(2026, 10, 2)   # same window as the dataset
RETURN_START, RETURN_END = datetime(2026, 10, 7), datetime(2026, 10, 16)
ORDERS_PER_PRODUCT, RETURNS_PER_PRODUCT = 34, 6

SHOE_SIZES = {"6": 24.5, "7": 25.5, "8": 26.5, "9": 27.5, "10": 28.5}
PRODUCTS = [
    # id, category, name, description, attributes, price range, variant factory key
    ("FW01", "footwear", "TrailRun Sneakers", "Lightweight trail running sneakers with a grip rubber sole.",
     {"material": "mesh", "sole": "rubber", "color": ["grey", "black"],
      "size_chart": {s: {"foot_length_cm": v} for s, v in SHOE_SIZES.items()}}, (2199, 2899), "shoe"),
    ("FW02", "footwear", "Classic Leather Loafers", "Formal leather loafers with a stitched leather sole.",
     {"material": "leather", "sole": "leather", "color": ["brown", "black"],
      "size_chart": {s: {"foot_length_cm": v} for s, v in SHOE_SIZES.items()}}, (2999, 3699), "shoe"),
    ("FW03", "footwear", "Everyday Slides", "Soft EVA slides for daily wear.",
     {"material": "EVA", "sole": "EVA", "color": ["navy", "black"],
      "size_chart": {s: {"foot_length_cm": v} for s, v in SHOE_SIZES.items()}}, (399, 799), "shoe"),
    ("EL01", "electronics_accessories", "Slim Phone Case", "Slim TPU protective case with a raised camera edge.",
     {"material": "TPU", "color": ["midnight_blue", "black"], "compatible_models": ["Pixel 8", "Pixel 9"]}, (399, 699), "phone"),
    ("EL02", "electronics_accessories", "USB-C Fast Charging Cable 1m", "Braided 1 m USB-C cable, 60 W fast charging.",
     {"material": "nylon braid", "color": ["black", "white"], "compatible_models": ["Pixel 8", "Pixel 9"], "length_m": 1}, (349, 599), "phone"),
    ("EL03", "electronics_accessories", "Tempered Glass Screen Protector", "9H tempered glass screen protector, easy-apply frame.",
     {"material": "tempered glass", "color": ["clear"], "compatible_models": ["Pixel 8", "Pixel 9"]}, (299, 499), "phone"),
]

CAUSE_WEIGHTS = {
    "footwear": {"size_fit": 35, "defect_quality": 25, "changed_mind": 15, "damaged_in_transit": 10, "not_as_described": 10, "wrong_item": 5},
    "electronics_accessories": {"defect_quality": 30, "not_as_described": 25, "changed_mind": 20, "damaged_in_transit": 15, "wrong_item": 10},
}
COMMENTS = {
    ("footwear", "size_fit"): ["Ordered size {s} but it runs small, toes feel cramped.", "Too tight at the heel, the size does not match the chart."],
    ("footwear", "defect_quality"): ["The sole started peeling off at the toe within two weeks.", "Stitching on the upper came apart."],
    ("footwear", "damaged_in_transit"): ["Box arrived crushed and one shoe has a scuffed, torn upper."],
    ("footwear", "wrong_item"): ["Received a different model than the one I ordered."],
    ("footwear", "not_as_described"): ["The color is much darker than in the listing photos."],
    ("footwear", "changed_mind"): ["Changed my mind, I no longer need these."],
    ("electronics_accessories", "size_fit"): ["Does not fit my {m}: the camera cutout is misaligned."],
    ("electronics_accessories", "defect_quality"): ["Stopped working after about a week.", "Cracked right out of the box."],
    ("electronics_accessories", "damaged_in_transit"): ["The package was crushed and the item arrived cracked."],
    ("electronics_accessories", "wrong_item"): ["Received an accessory for a different phone model."],
    ("electronics_accessories", "not_as_described"): ["The color looks different from the photo.", "Not as sturdy as the listing says."],
    ("electronics_accessories", "changed_mind"): ["No longer need it."],
}


def _rand_dt(rng, a: datetime, b: datetime) -> datetime:
    return a + timedelta(seconds=rng.uniform(0, (b - a).total_seconds()))


def add() -> None:
    rng = random.Random(21)
    engine = create_engine(settings.app_url)
    with engine.begin() as c:
        if c.execute(text("SELECT count(*) FROM product WHERE id LIKE 'FW%' OR id LIKE 'EL%'")).scalar():
            raise SystemExit("Already added. Run with --remove first to add again.")
        for cat in ("footwear", "electronics_accessories"):
            if not c.execute(text("SELECT 1 FROM category_profile WHERE category = :c"), {"c": cat}).scalar():
                raise SystemExit(f"Missing category profile '{cat}'. Run: python -m scripts.load_dataset --profiles-only")
        seller = c.execute(text("SELECT id FROM seller ORDER BY id LIMIT 1")).scalar()
        customers = [r[0] for r in c.execute(text("SELECT id FROM customer"))]
        next_no = c.execute(text("SELECT coalesce(max(substr(id, 5)::int), 2000) FROM orders WHERE id LIKE 'ORD-2%'")).scalar()

        insert(c, "product", [dict(id=p[0], seller_id=seller, category=p[1], name=p[2], description=p[3],
                                   attributes=json.dumps(p[4]), listing_image_urls=[]) for p in PRODUCTS])

        orders, ships, returns = [], [], []
        for pid, cat, _name, _desc, attrs, (lo, hi), vkind in PRODUCTS:
            made = []
            for _ in range(ORDERS_PER_PRODUCT):
                next_no += 1
                odate = _rand_dt(rng, ORDER_START, ORDER_END)
                variant = ({"size": rng.choice(list(SHOE_SIZES)), "color": rng.choice(attrs["color"])} if vkind == "shoe"
                           else {"model": rng.choice(attrs["compatible_models"]), "color": rng.choice(attrs["color"])})
                o = dict(id=f"ORD-{next_no}", customer_id=rng.choice(customers), product_id=pid, variant=variant,
                         batch_id=rng.choice(BATCHES), price=round(rng.uniform(lo, hi), 2), order_date=odate,
                         delivered=odate + timedelta(days=rng.uniform(3, 6)), warehouse=rng.choice(WAREHOUSES), cause=None)
                made.append(o)
            for o in rng.sample(made, RETURNS_PER_PRODUCT):  # one return per order
                weights = CAUSE_WEIGHTS[cat]
                o["cause"] = rng.choices(list(weights), weights=list(weights.values()))[0]
            orders += made
            for o in made:
                ships.append(dict(id=f"SHP-{o['id'][4:]}", order_id=o["id"], warehouse=o["warehouse"], shipped_at=None,
                                  delivered_date=o["delivered"],
                                  damage_flag=bool(o["cause"] == "damaged_in_transit" and rng.random() < 0.7)))
            for o in made:
                if not o["cause"]:
                    continue
                cause = o["cause"]
                stated = cause
                if cause != "changed_mind" and rng.random() < 0.25:  # customer picks the wrong reason; the comment shows the symptom
                    stated = rng.choice([x for x in ("size_fit", "changed_mind", "other") if x != cause])
                cat_comments = COMMENTS[(cat, cause)]
                comment = rng.choice(cat_comments).format(s=o["variant"].get("size", ""), m=o["variant"].get("model", ""))
                created = max(_rand_dt(rng, RETURN_START, RETURN_END), o["delivered"] + timedelta(days=1))
                returns.append(dict(order=o, cause=cause, stated=stated, comment=comment, created=created, cat=cat))

        c.execute(text("""INSERT INTO orders (id, customer_id, product_id, variant, batch_id, price, order_date)
                          VALUES (:id, :customer_id, :product_id, CAST(:variant AS jsonb), :batch_id, :price, :order_date)"""),
                  [{k: (json.dumps(v) if k == "variant" else v) for k, v in o.items() if k in
                    ("id", "customer_id", "product_id", "variant", "batch_id", "price", "order_date")} for o in orders])
        insert(c, "shipment", ships)

        rids = alloc(c, "returns_seq", "r_", len(returns))
        mids = alloc(c, "media_seq", "m_", len(returns))
        media_rows = []
        for r, rid, mid in zip(returns, rids, mids):
            r["id"] = rid
            o = r["order"]
            sample = None
            if r["cause"] == "damaged_in_transit":
                sample = SAMPLES / "damaged_parcel_1.jpg"
            elif r["cat"] == "footwear" and r["cause"] == "defect_quality":
                sample = SAMPLES / f"worn_shoe_{rng.randint(1, 3)}.jpg"
            if sample and sample.exists():
                rel = f"returns/{o['product_id']}/{rid}/{rid}_defect.jpg"
                dest = Path(storage.root) / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(sample, dest)
                media_rows.append(dict(id=mid, return_id=rid, type="photo", storage_url=f"{storage.scheme}{rel}",
                                       mime_type="image/jpeg", size_bytes=dest.stat().st_size, created_at=r["created"]))
        insert(c, "returns", [dict(id=r["id"], order_id=r["order"]["id"], product_id=r["order"]["product_id"],
                                   customer_id=r["order"]["customer_id"], stated_reason=r["stated"], comment=r["comment"],
                                   status="pending_analysis", created_at=r["created"], status_updated_at=r["created"])
                              for r in returns])
        insert(c, "return_media", media_rows)
        labels = [dict(id=i, subject_type="return", subject_id=r["id"], true_root_cause=r["cause"],
                       scenario="synthetic_category_data") for r, i in zip(returns, alloc(c, "eval_seq", "ev_", len(returns)))]
        c.execute(text("""INSERT INTO eval_label (id, subject_type, subject_id, true_root_cause, scenario)
                          VALUES (:id, :subject_type, :subject_id, CAST(:true_root_cause AS root_cause), :scenario)"""), labels)
    mism = sum(r["stated"] != r["cause"] for r in returns)
    print(f"added {len(PRODUCTS)} products, {len(orders)} orders, {len(returns)} returns "
          f"({mism} with a stated reason that differs from the true cause, {len(media_rows)} with a photo)")


def remove() -> None:
    engine = create_engine(settings.app_url)
    with engine.begin() as c:
        pids = [r[0] for r in c.execute(text("SELECT id FROM product WHERE id LIKE 'FW%' OR id LIKE 'EL%'"))]
        if not pids:
            print("nothing to remove"); return
        rids = [r[0] for r in c.execute(text("SELECT id FROM returns WHERE product_id = ANY(:p)"), {"p": pids})]
        c.execute(text("DELETE FROM eval_label WHERE subject_type = 'return' AND subject_id = ANY(:r)"), {"r": rids})
        c.execute(text("DELETE FROM agent_run WHERE subject_type = 'return' AND subject_id = ANY(:r)"), {"r": rids})
        c.execute(text("DELETE FROM returns WHERE product_id = ANY(:p)"), {"p": pids})   # cascades media, analyses, findings, reviews
        c.execute(text("DELETE FROM shipment WHERE order_id IN (SELECT id FROM orders WHERE product_id = ANY(:p))"), {"p": pids})
        c.execute(text("DELETE FROM orders WHERE product_id = ANY(:p)"), {"p": pids})
        c.execute(text("DELETE FROM product WHERE id = ANY(:p)"), {"p": pids})
    for pid in pids:
        shutil.rmtree(Path(storage.root) / "returns" / pid, ignore_errors=True)
    print(f"removed {len(pids)} products and everything attached to them")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    remove() if ap.parse_args().remove else add()
