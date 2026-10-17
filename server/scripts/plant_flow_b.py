"""Plant Flow B demo scenarios on top of the base dataset. Adds rows only; never edits existing ones.

1. A previous 90-day window of orders and returns for every product, at about each product's
   current return rate, so trends and "change vs previous period" have something to compare with.
2. Four scenarios from the design, each with ground truth in eval_label (subject_type='product'):
     flowb_size_chart        apparel      size chart overstates length for L/M since a chart change
     flowb_defective_batch   footwear     sole separation concentrated in one batch
     flowb_misleading_photo  apparel      listing photo retouched; colour duller than shown
     flowb_transit_damage    electronics  glass cracked in transit, mostly from one warehouse

Run after the base data and the Flow B schema exist:
    python -m scripts.plant_flow_b
It prints the REPORT_AS_OF to put in .env so the scenarios stay inside the 90-day window.
Idempotent: does nothing if the scenarios are already planted.
"""
import json
import random
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

from app.core.config import settings

rng = random.Random(42)
REVIEWER = "seed-reviewer"

DEFAULT_MIX = {"size_fit": 30, "changed_mind": 25, "defect_quality": 12, "not_as_described": 12,
               "damaged_in_transit": 8, "wrong_item": 5, "other": 8}
COMMENTS = {
    "size_fit": ["Runs a bit small for me.", "Did not fit well, exchanging for another size.", "Too loose around the waist."],
    "changed_mind": ["Decided I don't need it anymore.", "Bought a different one instead.", "Ordered by mistake."],
    "defect_quality": ["Small defect near the seam.", "Stopped working properly after a few days.", "Material started pilling quickly."],
    "not_as_described": ["Not quite what the description said.", "Material feels different from the listing."],
    "damaged_in_transit": ["Arrived with a damaged box.", "Item was scratched on arrival."],
    "wrong_item": ["Received a different item.", "Wrong variant was delivered."],
    "other": ["Delivery took too long.", "No longer needed after the event."],
}


def as_of_for(db) -> datetime:
    """Start of the day after the newest order or return: every planted row lands before it."""
    return db.execute(text("""SELECT date_trunc('day', greatest(
                                  (SELECT max(order_date) FROM orders), (SELECT max(created_at) FROM returns)))
                              + interval '1 day'""")).scalar_one()


class Planter:
    def __init__(self, db, as_of: datetime):
        self.db, self.as_of = db, as_of
        self.customers = db.execute(text("SELECT id FROM customer ORDER BY id")).scalars().all()
        self.n = Counter()

    # ── lookups ──
    def product(self, prefer: str, category: str) -> dict | None:
        row = self.db.execute(text("""SELECT id, category, attributes FROM product
                                      WHERE id = :p OR category = :c ORDER BY (id = :p) DESC, id LIMIT 1"""),
                              {"p": prefer, "c": category}).mappings().first()
        if not row:
            return None
        info = self.db.execute(text("""SELECT avg(price) AS price, array_agg(DISTINCT batch_id) AS batches,
                                              jsonb_agg(DISTINCT variant) AS variants
                                       FROM orders WHERE product_id = :p"""), {"p": row["id"]}).mappings().one()
        return dict(row) | {"price": float(info["price"] or 999), "batches": sorted(b for b in info["batches"] or [] if b),
                            "variants": info["variants"] or [{}]}

    def variant(self, p: dict, **want) -> dict:
        ok = [v for v in p["variants"] if all(v.get(k) == x for k, x in want.items())]
        return dict(rng.choice(ok)) if ok else {**rng.choice(p["variants"]), **want}

    def media_url(self, product_id: str) -> str | None:
        files = sorted((Path(settings.media_dir) / "returns" / product_id).glob("*/*.jpg"))
        return f"local://{files[0].relative_to(settings.media_dir).as_posix()}" if files else None

    # ── writers ──
    def order(self, prefix: str, p: dict, variant: dict, when: datetime, batch: str | None = None,
              warehouse: str | None = None, damage: bool = False) -> dict:
        self.n[prefix] += 1
        oid, sid = f"ORD-{prefix}{self.n[prefix]:04d}", f"SHP-{prefix}{self.n[prefix]:04d}"
        self.db.execute(text("""INSERT INTO orders (id, customer_id, product_id, variant, batch_id, price, order_date)
                                VALUES (:id, :c, :p, CAST(:v AS jsonb), :b, :price, :d)"""),
                        dict(id=oid, c=rng.choice(self.customers), p=p["id"], v=json.dumps(variant),
                             b=batch or rng.choice(p["batches"] or ["B31"]),
                             price=round(p["price"] * rng.uniform(0.95, 1.05), 2), d=when))
        self.db.execute(text("""INSERT INTO shipment (id, order_id, warehouse, shipped_at, delivered_date, damage_flag)
                                VALUES (:id, :o, :w, :s, :d, :dmg)"""),
                        dict(id=sid, o=oid, w=warehouse or rng.choice(["Delhi", "Pune", "Bengaluru"]),
                             s=when + timedelta(days=1), d=when + timedelta(days=4), dmg=damage))
        return {"id": oid, "product_id": p["id"], "date": when}

    def ret(self, order: dict, cause: str, comment: str, stated: str | None = None, note: str | None = None,
            reviewed: bool = True, finding: tuple | None = None, media_url: str | None = None) -> str:
        stated = stated or (cause if cause != "suspicious" else "other")
        created = min(order["date"] + timedelta(days=rng.randint(4, 10)), self.as_of - timedelta(hours=6))
        customer = self.db.execute(text("SELECT customer_id FROM orders WHERE id = :o"), {"o": order["id"]}).scalar_one()
        rid = self.db.execute(text("""
            INSERT INTO returns (order_id, product_id, customer_id, stated_reason, comment, status, created_at, status_updated_at)
            VALUES (:o, :p, :c, CAST(:s AS root_cause), :cm, CAST(:st AS return_status), :t, :t2) RETURNING id"""),
            dict(o=order["id"], p=order["product_id"], c=customer, s=stated, cm=comment,
                 st="reviewed" if reviewed else "awaiting_review", t=created, t2=created + timedelta(days=1))).scalar_one()
        aid = self.db.execute(text("""
            INSERT INTO return_analysis (return_id, root_cause, reason_mismatch, confidence, explanation, evidence,
                                         recommended_action, needs_manual_review, model_version, created_at)
            VALUES (:r, CAST(:c AS root_cause), :mm, :conf, :ex, CAST(:ev AS jsonb), 'approve_return', false, 'seed-flowb', :t)
            RETURNING id"""),
            dict(r=rid, c=cause, mm=stated != cause, conf=round(rng.uniform(0.74, 0.92), 2), t=created + timedelta(hours=1),
                 ex=(f"Customer selected '{stated}' but the evidence indicates {cause}." if stated != cause
                     else f"Stated reason '{stated}' is consistent with the comment and order context."),
                 ev=json.dumps([{"ref": order["id"], "finding": "Order context checked"}]))).scalar_one()
        if media_url:
            mid = self.db.execute(text("""INSERT INTO return_media (return_id, type, storage_url, mime_type, created_at)
                                          VALUES (:r, 'photo', :u, 'image/jpeg', :t) RETURNING id"""),
                                  dict(r=rid, u=media_url, t=created)).scalar_one()
            if finding:
                dtype, sev, damage, matches, desc = finding
                self.db.execute(text("""INSERT INTO media_finding (analysis_id, return_id, media_id, defect_type, severity,
                                                                   visible_damage, matches_listing, description)
                                        VALUES (:a, :r, :m, :d, CAST(:s AS severity_level), :v, :ml, :desc)"""),
                                dict(a=aid, r=rid, m=mid, d=dtype, s=sev, v=damage, ml=matches, desc=desc))
        if reviewed:
            self.db.execute(text("""INSERT INTO return_review (return_id, analysis_id, decision, final_root_cause, note, reviewer, reviewed_at)
                                    VALUES (:r, :a, 'accepted', CAST(:c AS root_cause), :n, :who, :t)"""),
                            dict(r=rid, a=aid, c=cause, n=note, who=REVIEWER, t=created + timedelta(days=1)))
        return rid

    def label(self, product_id: str, cause: str, scenario: str, note: str) -> None:
        self.db.execute(text("""INSERT INTO eval_label (subject_type, subject_id, true_root_cause, scenario, note)
                                VALUES ('product', :p, CAST(:c AS root_cause), :s, :n)"""),
                        dict(p=product_id, c=cause, s=scenario, n=note))

    def listing_change(self, product_id: str, field: str, old, new, when: datetime) -> None:
        self.db.execute(text("""INSERT INTO listing_change (product_id, field, old_value, new_value, changed_at)
                                VALUES (:p, :f, :o, :n, :t)"""),
                        dict(p=product_id, f=field, o=json.dumps(old), n=json.dumps(new), t=when))

    def when(self, start: datetime, end: datetime) -> datetime:
        return start + (end - start) * rng.random()

    # ── 1. previous window for every product ──
    def history(self, planted: set[str]) -> int:
        cur_start, prev_start = self.as_of - timedelta(days=90), self.as_of - timedelta(days=180)
        rows = self.db.execute(text("""
            SELECT p.id, count(DISTINCT o.id) AS orders, count(DISTINCT r.id) AS returns
            FROM product p LEFT JOIN orders o ON o.product_id = p.id AND o.order_date >= :s
            LEFT JOIN returns r ON r.order_id = o.id GROUP BY p.id ORDER BY p.id"""), {"s": cur_start}).mappings().all()
        added = 0
        for row in rows:
            p = self.product(row["id"], "")
            mix = dict(self.db.execute(text("""SELECT cause::text, count(*) FROM v_return_effective_cause
                                               WHERE product_id = :p AND cause IS NOT NULL AND cause <> 'suspicious'
                                               GROUP BY 1"""), {"p": p["id"]}).all()) or DEFAULT_MIX
            if p["id"] in planted:  # before the problem started: a lower rate, the ordinary mix
                rate, mix = 0.12, DEFAULT_MIX
            else:  # about the same as now, so these products stay "healthy"
                rate = (row["returns"] / row["orders"] if row["orders"] else 0.18) * rng.uniform(0.9, 1.05)
            n_orders = max(20, round((row["orders"] or 30) * rng.uniform(0.9, 1.1)))
            n_returns = round(n_orders * rate)
            causes = rng.choices(list(mix), weights=list(mix.values()), k=n_returns)
            for i in range(n_orders):
                o = self.order("H", p, self.variant(p), self.when(prev_start, cur_start - timedelta(days=1)))
                if i < n_returns:
                    self.ret(o, causes[i], rng.choice(COMMENTS[causes[i]]), note="Checked against photos and comment.")
                    added += 1
        return added

    # ── 2. scenarios ──
    def size_chart(self, p: dict) -> None:
        changed = self.as_of - timedelta(days=70)
        chart = (p["attributes"] or {}).get("size_chart") or {}
        new = {s: chart[s] for s in ("L", "M") if s in chart}
        old = {s: {k: (v - 3 if k == "length_cm" else v) for k, v in m.items()} for s, m in new.items()}
        if new:
            self.listing_change(p["id"], "attributes.size_chart", old, new, changed)
        url = self.media_url(p["id"])
        comments = ["Ordered {s}, fits like a size smaller. Much shorter than the chart.",
                    "Length is about 3 cm shorter than the size chart says for {s}.",
                    "Too short in the body compared to the listed length.",
                    "Measured it: shorter than the chart. Had to return."]
        notes = ["Photo shows length ~3 cm shorter than chart", "Confirmed: garment shorter than listed length",
                 "Measuring tape photo matches the complaint"]
        finding = ("measurement_gap", "medium", False, False, "Garment length visibly shorter than the listed chart length")
        sizes = ["L"] * 8 + ["M"] * 4 + ["S", "XL"]
        for i, size in enumerate(sizes):
            o = self.order("S", p, self.variant(p, size=size), self.when(changed + timedelta(days=3), self.as_of - timedelta(days=12)))
            self.ret(o, "size_fit", rng.choice(comments).format(s=size), note=rng.choice(notes),
                     reviewed=i >= 2, finding=finding, media_url=url)
        for _ in range(12):
            self.order("S", p, self.variant(p), self.when(changed, self.as_of - timedelta(days=5)))
        self.label(p["id"], "size_fit", "flowb_size_chart",
                   "Size chart length for L and M overstated by ~3 cm since the chart change; correct the chart.")

    def defective_batch(self, p: dict) -> None:
        bad = "B36" if "B36" in p["batches"] else (p["batches"] or ["B36"])[0]
        others = [b for b in p["batches"] if b != bad] or [bad]
        start = self.as_of - timedelta(days=60)
        url = self.media_url(p["id"])
        comments = ["Sole started separating at the toe after a week.", "The sole came off within days of normal use.",
                    "Glue failed, the sole is peeling away from the upper."]
        finding = ("sole_separation", "high", True, True, "Sole separating from the upper at the toe")
        for i in range(10):
            batch = bad if i < 8 else rng.choice(others)
            o = self.order("S", p, self.variant(p), self.when(start, self.as_of - timedelta(days=12)), batch=batch)
            mismatch = i in (3, 6)  # customer picked "doesn't fit"; the photo shows the sole coming off
            self.ret(o, "defect_quality",
                     "Didn't fit well and the sole started coming off." if mismatch else rng.choice(comments),
                     stated="size_fit" if mismatch else None, reviewed=i not in (1, 8), finding=finding, media_url=url,
                     note=f"Sole separation visible in photo; batch {batch}")
        for i in range(12):
            self.order("S", p, self.variant(p), self.when(start, self.as_of - timedelta(days=5)),
                       batch=bad if i < 3 else rng.choice(others))
        self.label(p["id"], "defect_quality", "flowb_defective_batch", f"Batch {bad} has a sole bonding defect.")

    def misleading_photo(self, p: dict) -> None:
        changed = self.as_of - timedelta(days=60)
        self.listing_change(p["id"], "listing_image_urls[0]", "original studio photo",
                            "retouched photo, colour saturation boosted", changed)
        url = self.media_url(p["id"])
        comments = ["Colour is much duller than in the listing photo.",
                    "Looks nothing like the picture, the shade is completely different.",
                    "The one in the photo is bright, the one I got looks faded."]
        notes = ["Customer photo shows a duller shade than listing photo 1", "Colour mismatch vs listing confirmed"]
        finding = ("color_variance", "medium", False, False, "Colour noticeably duller than the listing photo")
        for i in range(9):
            o = self.order("S", p, self.variant(p), self.when(changed + timedelta(days=2), self.as_of - timedelta(days=12)))
            self.ret(o, "not_as_described", rng.choice(comments), stated="changed_mind" if i in (2, 5) else None,
                     note=rng.choice(notes), reviewed=i != 4, finding=finding, media_url=url)
        for _ in range(11):
            self.order("S", p, self.variant(p), self.when(changed, self.as_of - timedelta(days=5)))
        self.label(p["id"], "not_as_described", "flowb_misleading_photo",
                   "Listing photo 1 was retouched; colour is oversaturated compared with the product.")

    def transit_damage(self, p: dict) -> None:
        bad = "Pune"
        start = self.as_of - timedelta(days=60)
        url = self.media_url(p["id"])
        comments = ["Box was crushed and the glass arrived cracked.", "Screen protector was shattered inside the package.",
                    "Package arrived dented, the glass is broken in two places."]
        finding = ("transit_damage", "high", True, True, "Glass cracked; outer packaging crushed")
        for i in range(9):
            wh = bad if i < 7 else rng.choice(["Delhi", "Bengaluru"])
            o = self.order("S", p, self.variant(p), self.when(start, self.as_of - timedelta(days=12)),
                           warehouse=wh, damage=wh == bad and i != 0)
            self.ret(o, "damaged_in_transit", rng.choice(comments), note=f"Courier box crushed; shipped from {wh}",
                     reviewed=i != 2, finding=finding, media_url=url)
        for _ in range(11):
            self.order("S", p, self.variant(p), self.when(start, self.as_of - timedelta(days=5)))
        self.label(p["id"], "damaged_in_transit", "flowb_transit_damage",
                   f"Glass breaks in transit from the {bad} warehouse; packaging/handling issue.")


SCENARIOS = [  # (method, preferred product, category)
    ("size_chart", "P19", "apparel"),
    ("defective_batch", "FW01", "footwear"),
    ("misleading_photo", "P17", "apparel"),
    ("transit_damage", "EL03", "electronics_accessories"),
]


def plant() -> None:
    engine = create_engine(settings.app_url)
    with engine.begin() as db:
        if db.execute(text("SELECT 1 FROM eval_label WHERE scenario LIKE 'flowb_%' LIMIT 1")).scalar():
            print("Flow B scenarios already planted; nothing to do")
            return
        as_of = as_of_for(db)
        planter = Planter(db, as_of)
        chosen = {}
        for method, prefer, category in SCENARIOS:
            p = planter.product(prefer, category)
            if p and p["id"] not in chosen.values():
                chosen[method] = p["id"]
        history = planter.history(set(chosen.values()))
        for method, pid in chosen.items():
            getattr(planter, method)(planter.product(pid, ""))
        print(f"planted: {history} previous-period returns; scenarios: "
              + ", ".join(f"{m} -> {pid}" for m, pid in chosen.items()))
        print(f"set REPORT_AS_OF={as_of.date().isoformat()} in .env so the scenarios stay inside the 90-day window")


if __name__ == "__main__":
    plant()
