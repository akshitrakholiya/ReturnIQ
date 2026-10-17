"""Synthetic demo data for ReturnIQ (deterministic, seed=42).

Planted scenarios (the ground truth is stored in eval_label, which no tool can read):
  p_shirt   Classic Cotton Shirt   size chart runs large      -> size_fit on sizes M/L
  p_kurta   Linen Kurta            transit damage             -> damaged_in_transit, WH-Bhiwandi
  p_sneaker TrailRun Sneakers      defective batch B36        -> defect_quality
  p_case    Phone Case (Midnight)  misleading listing photo   -> not_as_described, midnight_blue
  p_scarf   Silk Scarf             < 5 returns                -> "not enough data" report
  everything else                  healthy, near category average

Run via: python -m scripts.init_db --reset --seed
"""
import json
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text

from app.core.config import settings

NOW = datetime.now(timezone.utc)
rng = random.Random(42)

CATEGORIES = {
    "apparel": dict(
        variant_dimensions=["size", "color"],
        key_attributes=["size_chart", "material", "color"],
        media_focus="fit, length, color shade, stitching, stains",
        listing_checks=["size chart vs complaints", "listing color vs photo color"],
        cost=(90, 30, 0.25, 250), base_rate=0.11),
    "footwear": dict(
        variant_dimensions=["size", "color"],
        key_attributes=["size_chart", "material", "sole"],
        media_focus="sole condition, stitching, upper material, size label, scuffs",
        listing_checks=["size chart vs complaints", "batch defect concentration"],
        cost=(120, 40, 0.30, 400), base_rate=0.10),
    "electronics_accessories": dict(
        variant_dimensions=["model", "color"],
        key_attributes=["compatible_models", "material", "color"],
        media_focus="cracks, scratches, port/fit compatibility, color shade vs listing",
        listing_checks=["listing color vs photo color", "compatible models vs complaints"],
        cost=(70, 25, 0.20, 180), base_rate=0.07),
}

POLICIES = [
    ("1.1", "Return window", "Items can be returned within 30 days of delivery. Returns after 30 days are not eligible unless the item is defective."),
    ("2.1", "Defective items", "Defective items such as stitching failures, broken zippers, sole separation or non-working electronics are eligible for a full refund or replacement within 30 days of delivery."),
    ("2.2", "Damaged in transit", "Items that arrive damaged due to shipping, with visible packaging or product damage, are eligible for a full refund. Photo evidence is required."),
    ("2.3", "Wrong item delivered", "If the item delivered differs from the item ordered in product, size or color, the customer is eligible for a free exchange or full refund."),
    ("2.4", "Size and fit", "Size and fit returns are accepted within 30 days if the item is unworn, unwashed and has original tags. One free size exchange per order."),
    ("2.5", "Not as described", "If the item materially differs from its listing, including color shade, material or dimensions, the return is approved and the seller is notified."),
    ("3.1", "Change of mind", "Change-of-mind returns are accepted within 10 days of delivery if the item is unused and in original packaging. Return shipping is charged to the customer."),
    ("3.2", "Suspicious returns", "Returns with signs of misuse, mismatched or reused items, or a pattern of repeated returns are sent for manual review and may be rejected."),
    ("4.1", "Refund timelines", "Approved refunds are issued to the original payment method within 5 to 7 business days after the item is received."),
]
POLICY_BY_CAUSE = {
    "size_fit": "policy_2.4", "defect_quality": "policy_2.1", "damaged_in_transit": "policy_2.2",
    "wrong_item": "policy_2.3", "not_as_described": "policy_2.5", "changed_mind": "policy_3.1",
    "suspicious": "policy_3.2", "other": "policy_1.1",
}

WAREHOUSES = ["WH-Bhiwandi", "WH-Bengaluru", "WH-Gurugram"]
SIZES = ["S", "M", "L", "XL"]
SHOE_SIZES = ["6", "7", "8", "9", "10"]

# key, seller index, category, name, price, orders, description, attributes
PRODUCTS = [
    ("shirt", 0, "apparel", "Classic Cotton Shirt", 1299, 440,
     "Regular-fit cotton shirt for everyday wear.",
     {"material": "cotton", "color": ["white", "navy"],
      "size_chart": {"S": {"chest_cm": 96, "length_cm": 68}, "M": {"chest_cm": 101, "length_cm": 70},
                     "L": {"chest_cm": 106, "length_cm": 72}, "XL": {"chest_cm": 111, "length_cm": 74}}}),
    ("kurta", 0, "apparel", "Linen Kurta", 1599, 400,
     "Breathable linen kurta with mandarin collar.",
     {"material": "linen", "color": ["sand", "olive"],
      "size_chart": {"S": {"chest_cm": 94, "length_cm": 100}, "M": {"chest_cm": 99, "length_cm": 102},
                     "L": {"chest_cm": 104, "length_cm": 104}, "XL": {"chest_cm": 109, "length_cm": 106}}}),
    ("jacket", 0, "apparel", "Denim Jacket", 2999, 800,
     "Classic washed denim jacket.",
     {"material": "denim", "color": ["indigo", "black"],
      "size_chart": {"S": {"chest_cm": 100, "length_cm": 62}, "M": {"chest_cm": 105, "length_cm": 64},
                     "L": {"chest_cm": 110, "length_cm": 66}, "XL": {"chest_cm": 115, "length_cm": 68}}}),
    ("tee", 0, "apparel", "Cotton Tee", 599, 800,
     "Soft crew-neck cotton t-shirt.",
     {"material": "cotton", "color": ["white", "black"],
      "size_chart": {"S": {"chest_cm": 92, "length_cm": 66}, "M": {"chest_cm": 97, "length_cm": 68},
                     "L": {"chest_cm": 102, "length_cm": 70}, "XL": {"chest_cm": 107, "length_cm": 72}}}),
    ("scarf", 0, "apparel", "Silk Scarf", 899, 30,
     "Hand-finished silk scarf. New listing.",
     {"material": "silk", "color": ["red", "teal"]}),  # no size chart: completeness note
    ("sneaker", 1, "footwear", "TrailRun Sneakers", 2499, 420,
     "Lightweight trail running sneakers with grip sole.",
     {"material": "mesh", "sole": "rubber", "color": ["grey", "black"],
      "size_chart": {s: {"foot_length_cm": 24 + i} for i, s in enumerate(SHOE_SIZES)}}),
    ("loafer", 1, "footwear", "Leather Loafers", 3499, 330,
     "Formal leather loafers.",
     {"material": "leather", "sole": "leather", "color": ["brown", "black"],
      "size_chart": {s: {"foot_length_cm": 24 + i} for i, s in enumerate(SHOE_SIZES)}}),
    ("flipflop", 1, "footwear", "Flip Flops", 399, 330,
     "Everyday rubber flip flops.",
     {"material": "rubber", "sole": "rubber", "color": ["blue", "black"],
      "size_chart": {s: {"foot_length_cm": 24 + i} for i, s in enumerate(SHOE_SIZES)}}),
    ("case", 2, "electronics_accessories", "Phone Case Midnight", 499, 440,
     "Slim protective phone case in midnight blue or black.",
     {"material": "TPU", "color": ["midnight_blue", "black"], "compatible_models": ["Pixel 8", "Pixel 9"]}),
    ("cable", 2, "electronics_accessories", "USB-C Cable 1m", 349, 330,
     "Braided 1m USB-C fast charging cable.",
     {"material": "nylon", "color": ["black", "white"], "length_m": 1}),
    ("guard", 2, "electronics_accessories", "Screen Guard", 299, 330,
     "Tempered glass screen guard.",
     {"material": "tempered glass", "color": ["clear"], "compatible_models": ["Pixel 8", "Pixel 9"]}),
]

FIRST = ["Aarav", "Vivaan", "Aditya", "Ishaan", "Rohan", "Karan", "Neha", "Priya", "Ananya", "Diya",
         "Kavya", "Meera", "Sneha", "Pooja", "Rahul", "Amit", "Sanjay", "Anjali", "Riya", "Tanvi"]
LAST = ["Sharma", "Patel", "Mehta", "Iyer", "Nair", "Reddy", "Gupta", "Singh", "Kapoor", "Joshi",
        "Desai", "Kulkarni", "Bose", "Das", "Rao"]

COMMENTS = {
    "size_fit": ["Too tight in the chest, size {s} feels smaller than expected.",
                 "Length is shorter than the size chart says.", "Does not fit, runs different from the chart.",
                 "Ordered {s} as per chart but it is too loose."],
    "defect_quality": ["Stitching came apart after two days.", "The sole started separating at the toe.",
                       "Product stopped working properly.", "Poor quality, material is peeling."],
    "damaged_in_transit": ["Package arrived crushed and the item is torn.", "Item was damaged when I opened the box.",
                           "Box was wet and torn, product damaged."],
    "wrong_item": ["Received a different color than ordered.", "Wrong size sent."],
    "not_as_described": ["Color looks different from the photo, much lighter.", "Does not look like the listing.",
                         "The shade is more purple than the picture shows."],
    "changed_mind": ["Changed my mind.", "No longer need it.", "Found a better price elsewhere."],
    "suspicious": ["Item not needed anymore."],
    "other": ["Not satisfied."],
}
BASE_CAUSE_WEIGHTS = {"size_fit": 28, "defect_quality": 18, "damaged_in_transit": 8, "wrong_item": 6,
                      "not_as_described": 12, "changed_mind": 24, "suspicious": 2, "other": 2}


def pick(weights: dict):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def alloc(conn, seq: str, prefix: str, n: int) -> list[str]:
    if n == 0:
        return []
    rows = conn.execute(text(f"SELECT nextval('{seq}') FROM generate_series(1, :n)"), {"n": n}).all()
    return [f"{prefix}{r[0]}" for r in rows]


def insert(conn, table: str, rows: list[dict]):
    if not rows:
        return
    cols = list(rows[0])
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
    conn.execute(text(sql), rows)


def order_params(key, category, age_days, variant, batch, wh):
    """Return (probability of return, cause weights) for one order."""
    recent = age_days <= 90
    base = CATEGORIES[category]["base_rate"]
    w = dict(BASE_CAUSE_WEIGHTS)
    if key == "shirt":
        if variant["size"] in ("M", "L"):
            return (0.46 if recent else 0.22), {"size_fit": 85, "changed_mind": 8, "defect_quality": 4, "other": 3}
        return 0.06, w
    if key == "kurta" and wh == "WH-Bhiwandi":
        return (0.55 if recent else 0.25), {"damaged_in_transit": 85, "changed_mind": 8, "size_fit": 5, "other": 2}
    if key == "kurta":
        return 0.07, w
    if key == "sneaker" and batch == "B36":
        return 0.42, {"defect_quality": 85, "changed_mind": 7, "size_fit": 6, "other": 2}
    if key == "sneaker":
        return 0.08, w
    if key == "case" and variant["color"] == "midnight_blue":
        return (0.38 if recent else 0.12), {"not_as_described": 85, "changed_mind": 8, "defect_quality": 5, "other": 2}
    if key == "case":
        return 0.06, w
    if key == "scarf":
        return 0.04, w
    return base, w


def media_finding(cause, key, matches_ok=True):
    """(defect_type, severity, visible_damage, matches_listing, description)"""
    if cause == "size_fit":
        if key == "shirt":
            return ("length_shorter_than_chart", "low", False, False,
                    "Garment length measures 3-4 cm shorter than the listed size chart.")
        return ("fit_issue", "none", False, True, "No visible defect; fit complaint only.")
    if cause == "defect_quality":
        if key == "sneaker":
            return ("sole_separation", "high", True, True, "Sole detached from the upper at the toe.")
        return ("stitching_failure", "medium", True, True, "Visible loose or broken stitching.")
    if cause == "damaged_in_transit":
        return ("transit_damage", "high", True, True, "Torn fabric and crushed packaging consistent with transit damage.")
    if cause == "wrong_item":
        return ("wrong_item", "none", False, False, "Item in photo differs from the ordered variant.")
    if cause == "not_as_described":
        if key == "case":
            return ("color_mismatch", "medium", False, False, "Case shade is lighter and more purple than the listing photo.")
        return ("not_as_described", "low", False, False, "Item differs from the listing.")
    return ("none", "none", False, True, "No visible defect; item appears unused.")


def seed():
    engine = create_engine(settings.app_url)
    with engine.begin() as c:
        # ── reference data ──
        for cat, p in CATEGORIES.items():
            c.execute(text("""INSERT INTO category_profile
                (category, variant_dimensions, key_attributes, media_focus, listing_checks)
                VALUES (:c, CAST(:vd AS jsonb), CAST(:ka AS jsonb), :mf, CAST(:lc AS jsonb))"""),
                      dict(c=cat, vd=json.dumps(p["variant_dimensions"]), ka=json.dumps(p["key_attributes"]),
                           mf=p["media_focus"], lc=json.dumps(p["listing_checks"])))
        for sec, title, body in POLICIES:
            c.execute(text("INSERT INTO policy (id, section, title, text) VALUES (:i, :s, :t, :b)"),
                      dict(i=f"policy_{sec}", s=sec, t=title, b=body))

        seller_ids = [c.execute(text("INSERT INTO seller (name) VALUES (:n) RETURNING id"), dict(n=n)).scalar()
                      for n in ("Urban Threads", "StrideCo", "GadgetNest")]

        # ── customers (a few serial returners at the end) ──
        n_cust = 400
        cust_ids = alloc(c, "customer_seq", "c_", n_cust)
        insert(c, "customer", [dict(
            id=cid, name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
            email=f"user{i}@example.com", phone=f"+91{rng.randint(7000000000, 9999999999)}",
            created_at=NOW - timedelta(days=rng.randint(200, 700))) for i, cid in enumerate(cust_ids)])
        serial_returners = cust_ids[-3:]

        # ── products ──
        product_ids = {}
        for key, si, cat, name, price, n, desc, attrs in PRODUCTS:
            pid = c.execute(text("""INSERT INTO product (seller_id, category, name, description, attributes, listing_image_urls)
                VALUES (:s, :c, :n, :d, CAST(:a AS jsonb), :imgs) RETURNING id"""),
                            dict(s=seller_ids[si], c=cat, n=name, d=desc, a=json.dumps(attrs),
                                 imgs=[f"gs://returniq-dev-media/listings/{key}_{i}.jpg" for i in (1, 2)])).scalar()
            product_ids[key] = pid

        # ── orders, shipments, returns ──
        orders, shipments, returns_plan = [], [], []
        prod_meta = {k: (cat, price) for k, _, cat, _, price, *_ in PRODUCTS}
        for key, _, cat, name, price, n, _, attrs in PRODUCTS:
            for _ in range(n):
                age = rng.uniform(3, 180)
                if cat == "apparel":
                    variant = {"size": rng.choice(SIZES), "color": rng.choice(attrs["color"])}
                elif cat == "footwear":
                    variant = {"size": rng.choice(SHOE_SIZES), "color": rng.choice(attrs["color"])}
                else:
                    variant = {"model": rng.choice(attrs.get("compatible_models", ["generic"])),
                               "color": rng.choice(attrs["color"])}
                if key == "sneaker":
                    batch = "B36" if age <= 75 and rng.random() < 0.85 else ("B35" if age <= 135 else "B34")
                else:
                    batch = f"B{rng.randint(10, 14)}"
                wh = rng.choices(WAREHOUSES, weights=[40, 35, 25])[0]
                p, weights = order_params(key, cat, age, variant, batch, wh)
                cause = pick(weights) if age > 8 and rng.random() < p else None
                orders.append(dict(customer=rng.choice(cust_ids), key=key, variant=variant, batch=batch,
                                   price=price, age=age, wh=wh, cause=cause))
        # serial returners: a few extra suspicious returns on cheap items
        for cid in serial_returners:
            for key in ("guard", "cable", "flipflop"):
                orders.append(dict(customer=cid, key=key, variant={}, batch="B10", price=prod_meta[key][1],
                                   age=rng.uniform(10, 80), wh=WAREHOUSES[0], cause="suspicious"))
                if prod_meta[key][0] == "apparel":
                    orders[-1]["variant"] = {"size": "M", "color": "white"}
                elif prod_meta[key][0] == "footwear":
                    orders[-1]["variant"] = {"size": "8", "color": "black"}
                else:
                    orders[-1]["variant"] = {"model": "Pixel 8", "color": "black"}

        oids = alloc(c, "orders_seq", "o_", len(orders))
        shids = alloc(c, "shipment_seq", "sh_", len(orders))
        order_rows, ship_rows = [], []
        for o, oid, shid in zip(orders, oids, shids):
            o["id"] = oid
            odate = NOW - timedelta(days=o["age"])
            o["delivered"] = odate + timedelta(days=rng.uniform(2, 6))
            order_rows.append(dict(id=oid, customer_id=o["customer"], product_id=product_ids[o["key"]],
                                   variant=json.dumps(o["variant"]), batch_id=o["batch"], price=o["price"], order_date=odate))
            if rng.random() > 0.03:  # ~3% of orders have no shipment record (completeness note)
                dmg = (o["cause"] == "damaged_in_transit") if o["cause"] else rng.random() < 0.01
                ship_rows.append(dict(id=shid, order_id=oid, warehouse=o["wh"], shipped_at=odate + timedelta(days=1),
                                      delivered_date=o["delivered"] if o["delivered"] < NOW else None, damage_flag=dmg))
        c.execute(text("""INSERT INTO orders (id, customer_id, product_id, variant, batch_id, price, order_date)
                          VALUES (:id, :customer_id, :product_id, CAST(:variant AS jsonb), :batch_id, :price, :order_date)"""),
                  order_rows)
        insert(c, "shipment", ship_rows)

        # returns
        ret = []
        for o in orders:
            if o["cause"]:
                created = min(o["delivered"] + timedelta(days=rng.uniform(1, 8)), NOW - timedelta(hours=rng.uniform(1, 48)))
                ret.append(dict(order=o, cause=o["cause"], created=created))
        ret.sort(key=lambda r: r["created"], reverse=True)  # newest first
        rids = alloc(c, "returns_seq", "r_", len(ret))
        n_pending, n_awaiting = 6, 8
        for i, (r, rid) in enumerate(zip(ret, rids)):
            r["id"] = rid
            r["status"] = ("pending_analysis" if i < n_pending else
                           "analysis_failed" if i == n_pending else
                           "awaiting_review" if i < n_pending + n_awaiting else "reviewed")
            o = r["order"]
            cause = r["cause"]
            if cause == "suspicious":
                stated = "changed_mind"
            else:
                mism = 0.35 if (o["key"] == "sneaker" and cause == "defect_quality") else 0.10
                stated = rng.choice(["size_fit", "changed_mind", "other"]) if rng.random() < mism and cause != "changed_mind" else cause
            r["stated"] = stated
            r["comment"] = rng.choice(COMMENTS[stated]).format(s=o["variant"].get("size", ""))

        insert(c, "returns", [dict(
            id=r["id"], order_id=r["order"]["id"], product_id=product_ids[r["order"]["key"]],
            customer_id=r["order"]["customer"], stated_reason=r["stated"], comment=r["comment"],
            status=r["status"], created_at=r["created"], status_updated_at=r["created"]) for r in ret])

        # media (the newest pending return gets none -> "no media" completeness note)
        media_rows = []
        for i, r in enumerate(ret):
            n_media = 0 if i == 0 else (1 if rng.random() < 0.3 else rng.choice([2, 2, 3]))
            r["media"] = []
            for _ in range(n_media):
                r["media"].append(dict(type="video" if rng.random() < 0.08 else "photo"))
        mids = alloc(c, "media_seq", "m_", sum(len(r["media"]) for r in ret))
        k = 0
        for r in ret:
            for j, m in enumerate(r["media"]):
                m["id"] = mids[k]; k += 1
                ext, mime = ("mp4", "video/mp4") if m["type"] == "video" else ("jpg", "image/jpeg")
                media_rows.append(dict(id=m["id"], return_id=r["id"], type=m["type"],
                                       storage_url=f"gs://returniq-dev-media/returns/{r['id']}/{j + 1}.{ext}",
                                       mime_type=mime, size_bytes=rng.randint(200_000, 4_000_000), created_at=r["created"]))
        insert(c, "return_media", media_rows)

        # analyses, findings, reviews for everything past pending/failed
        analysed = [r for r in ret if r["status"] in ("awaiting_review", "reviewed")]
        aids = alloc(c, "analysis_seq", "ra_", len(analysed))
        run_ids = alloc(c, "run_seq", "run_", len(analysed) + 1)
        failed = next(r for r in ret if r["status"] == "analysis_failed")
        run_rows, an_rows, mf_rows, rv_rows, ev_rows = [], [], [], [], []
        for r, aid, runid in zip(analysed, aids, run_ids):
            o = r["order"]
            ai_cause = r["cause"]
            if rng.random() < 0.08:  # AI occasionally wrong
                ai_cause = rng.choice([c_ for c_ in ("size_fit", "defect_quality", "other", "changed_mind") if c_ != r["cause"]])
            conf = round(rng.uniform(0.78, 0.96), 2) if ai_cause == r["cause"] else round(rng.uniform(0.50, 0.75), 2)
            if rng.random() < 0.05:
                conf = round(rng.uniform(0.45, 0.59), 2)
            manual = conf < 0.60 or ai_cause == "suspicious"
            action = ("manual_review" if manual else
                      "reject_return" if ai_cause == "suspicious" else
                      "request_more_evidence" if conf < 0.70 else "approve_return")
            mismatch = r["stated"] != ai_cause
            ft = media_finding(ai_cause, o["key"])
            evidence = [{"ref": policy_ref, "finding": "Policy applies."} for policy_ref in [POLICY_BY_CAUSE[ai_cause]]]
            evidence.insert(0, {"ref": o["id"], "finding": f"Ordered {json.dumps(o['variant'])}, batch {o['batch']}"})
            if r["media"]:
                evidence.insert(0, {"ref": r["media"][0]["id"], "finding": ft[4]})
            notes = []
            if not r["media"]:
                notes.append("No media provided")
            if "size_chart" not in json.loads(json.dumps(PRODUCTS[[p[0] for p in PRODUCTS].index(o["key"])][7])):
                notes.append("Product has no size chart")
            run_rows.append(dict(id=runid, agent="return", subject_type="return", subject_id=r["id"], status="succeeded",
                                 model="gemini-2.5-flash", tool_calls=json.dumps([
                                     {"name": "analyze_media", "ms": rng.randint(2500, 9000)},
                                     {"name": "search_policy", "ms": rng.randint(20, 80)}]),
                                 started_at=r["created"], finished_at=r["created"] + timedelta(seconds=rng.randint(8, 28))))
            an_rows.append(dict(id=aid, return_id=r["id"], agent_run_id=runid, root_cause=ai_cause, reason_mismatch=mismatch,
                                confidence=conf,
                                explanation=(f"Customer selected '{r['stated']}' but the evidence indicates {ai_cause}." if mismatch
                                             else f"Stated reason '{r['stated']}' is consistent with the media and order context."),
                                evidence=json.dumps(evidence), context_notes=json.dumps(notes),
                                recommended_action=action, needs_manual_review=manual, model_version="gemini-2.5-flash",
                                created_at=r["created"] + timedelta(seconds=20)))
            for m in r["media"]:
                mf_rows.append(dict(analysis_id=aid, return_id=r["id"], media_id=m["id"], defect_type=ft[0], severity=ft[1],
                                    visible_damage=ft[2], matches_listing=ft[3], description=ft[4],
                                    created_at=r["created"] + timedelta(seconds=20)))
            if r["status"] == "reviewed":
                correct = ai_cause == r["cause"]
                rv_rows.append(dict(return_id=r["id"], analysis_id=aid, decision="accepted" if correct else "rejected",
                                    final_root_cause=r["cause"],
                                    note=None if correct else f"Actual cause is {r['cause']}.",
                                    reviewer=rng.choice(["reviewer_anita", "reviewer_dev"]),
                                    reviewed_at=min(r["created"] + timedelta(hours=rng.uniform(2, 36)), NOW)))
        # failed analysis: run row only
        run_rows.append(dict(id=run_ids[-1], agent="return", subject_type="return", subject_id=failed["id"], status="failed",
                             model="gemini-2.5-flash", tool_calls="[]", started_at=failed["created"],
                             finished_at=failed["created"] + timedelta(seconds=61)))
        for row in run_rows:
            row.setdefault("error", "Gemini timeout (>60 s)" if row["status"] == "failed" else None)
        c.execute(text("""INSERT INTO agent_run (id, agent, subject_type, subject_id, status, model, tool_calls, error, started_at, finished_at)
                          VALUES (:id, CAST(:agent AS agent_name), :subject_type, :subject_id, CAST(:status AS run_status), :model,
                                  CAST(:tool_calls AS jsonb), :error, :started_at, :finished_at)"""), run_rows)
        c.execute(text("""INSERT INTO return_analysis (id, return_id, agent_run_id, root_cause, reason_mismatch, confidence,
                          explanation, evidence, context_notes, recommended_action, needs_manual_review, model_version, created_at)
                          VALUES (:id, :return_id, :agent_run_id, CAST(:root_cause AS root_cause), :reason_mismatch, :confidence,
                          :explanation, CAST(:evidence AS jsonb), CAST(:context_notes AS jsonb),
                          CAST(:recommended_action AS recommended_action), :needs_manual_review, :model_version, :created_at)"""),
                  an_rows)
        insert(c, "media_finding", mf_rows)
        insert(c, "return_review", rv_rows)

        # ── eval labels (ground truth, never read by tools) ──
        scenario = {"shirt": "wrong_size_chart", "kurta": "transit_damage_wh_bhiwandi", "sneaker": "defective_batch_b36",
                    "case": "misleading_listing_photo"}
        labels = [dict(subject_type="return", subject_id=r["id"], true_root_cause=r["cause"],
                       scenario=scenario.get(r["order"]["key"])) for r in ret]
        labels += [dict(subject_type="product", subject_id=product_ids[k], true_root_cause=cs, scenario=sc)
                   for k, cs, sc in (("shirt", "size_fit", "wrong_size_chart"), ("kurta", "damaged_in_transit", "transit_damage_wh_bhiwandi"),
                                     ("sneaker", "defect_quality", "defective_batch_b36"),
                                     ("case", "not_as_described", "misleading_listing_photo"))]
        for lab, eid in zip(labels, alloc(c, "eval_seq", "ev_", len(labels))):
            lab["id"] = eid
        c.execute(text("""INSERT INTO eval_label (id, subject_type, subject_id, true_root_cause, scenario)
                          VALUES (:id, :subject_type, :subject_id, CAST(:true_root_cause AS root_cause), :scenario)"""), labels)

        # keep sequences consistent (alloc already advanced them) and report
        print(f"seeded: {len(orders)} orders, {len(ret)} returns, {len(media_rows)} media, "
              f"{len(an_rows)} analyses, {len(rv_rows)} reviews")


if __name__ == "__main__":
    seed()
