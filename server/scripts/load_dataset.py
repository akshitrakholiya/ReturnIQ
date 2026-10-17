"""Load the ReturnIQ dataset (docs/DataSet v1.1) into the Flow A schema.

    python -m scripts.init_db --reset        # empty schema (no synthetic seed)
    python -m scripts.load_dataset           # load dataset + copy its images

What it does (the dataset's JSON does not match our schema one-to-one):
  - order/return           -> orders/returns; the dataset's own IDs (ORD-1001, r_101, ...) are kept
  - customers              -> generated (the JSON has none); names are dummy
  - policies               -> ours (the JSON has none)
  - category profiles      -> the dataset's apparel, plus our footwear and electronics_accessories
  - decision 'approve_return' -> 'accepted'
  - each reviewed return gets a synthetic return_analysis (model_version 'dataset-v1.1') so the
    dataset's pre-computed media_findings have an analysis to belong to. It is NOT Return Agent output.
  - HOLDOUT returns are left as 'pending_analysis' with their photos only (no analysis, finding or
    review) so the Return Agent can be run on real photos and checked against eval_label.
  - eval_label gets the true cause of every return (the dataset's final_root_cause).
  - images: docs/DataSet v1.1/mock_storage -> <MEDIA_DIR>/ with the same folder layout.
Flow B only data (product reviews, cost model, listing changes) is not loaded.
"""
import argparse
import json
import random
import shutil
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

from app.core.config import settings
from app.services.storage import storage
from scripts.seed import CATEGORIES, FIRST, LAST, POLICIES, alloc, insert

SERVER_DIR = Path(__file__).resolve().parent.parent      # .../server
REPO_ROOT = SERVER_DIR.parent                              # docs/ and sample_images/ live next to server/ and web/
DEFAULT_DIR = REPO_ROOT / "docs" / "DataSet v1.1"
HOLDOUT = {"size_fit": 3, "not_as_described": 3, "defect_quality": 3,
           "damaged_in_transit": 3, "wrong_item": 3, "changed_mind": 2}  # newest returns of each cause
DECISION_MAP = {"approve_return": "accepted", "accepted": "accepted", "reject_return": "rejected", "rejected": "rejected"}


def storage_path(rel: str) -> str:
    """'./mock_storage/returns/P01/r_101/x.jpg' -> 'returns/P01/r_101/x.jpg' (key under MEDIA_DIR)."""
    return rel.replace("./", "", 1).removeprefix("mock_storage/")


def add_extra_profiles(c) -> int:
    """Category profiles the dataset does not define (it only has apparel). Existing rows are kept."""
    n = 0
    for cat, p in CATEGORIES.items():
        n += c.execute(text("""INSERT INTO category_profile (category, variant_dimensions, key_attributes, media_focus, listing_checks)
            VALUES (:c, CAST(:vd AS jsonb), CAST(:ka AS jsonb), :mf, CAST(:lc AS jsonb)) ON CONFLICT (category) DO NOTHING"""),
                       dict(c=cat, vd=json.dumps(p["variant_dimensions"]), ka=json.dumps(p["key_attributes"]),
                            mf=p["media_focus"], lc=json.dumps(p["listing_checks"]))).rowcount
    return n


def load(dataset_dir: Path, copy_images: bool = True) -> None:
    data_file = dataset_dir / "returniq_deepfashion_dataset.json"
    if not data_file.exists():
        raise SystemExit(f"Dataset not found: {data_file}\n"
                         "The dataset is not part of the repository (it is ~25 MB). Copy the 'DataSet v1.1' folder to "
                         f"{DEFAULT_DIR} or pass --dir <folder holding the JSON and mock_storage/>.\n"
                         "No dataset? Use the built-in synthetic data instead: python -m scripts.init_db --reset --seed")
    d = json.loads(data_file.read_text())
    rng = random.Random(7)
    engine = create_engine(settings.app_url)

    with engine.begin() as c:
        if c.execute(text("SELECT count(*) FROM product")).scalar():
            raise SystemExit("The database already has products. Run: python -m scripts.init_db --reset")

        for p in d["category_profiles"]:
            c.execute(text("""INSERT INTO category_profile (category, variant_dimensions, key_attributes, media_focus, listing_checks)
                VALUES (:c, CAST(:vd AS jsonb), CAST(:ka AS jsonb), :mf, CAST(:lc AS jsonb))"""),
                      dict(c=p["category"], vd=json.dumps(p["variant_dimensions"]), ka=json.dumps(p["key_attributes"]),
                           mf=p["media_focus"], lc=json.dumps(p["listing_checks"])))
        add_extra_profiles(c)  # footwear, electronics_accessories (apparel came from the dataset above)
        insert(c, "seller", [dict(id=s["id"], name=s["name"]) for s in d["sellers"]])
        insert(c, "policy", [dict(id=f"policy_{sec}", section=sec, title=t, text=b) for sec, t, b in POLICIES])

        # customers: the JSON references them but never defines them
        cust_ids = sorted({x["customer_id"] for k in ("orders", "returns") for x in d[k]})
        insert(c, "customer", [dict(id=i, name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                                    email=f"{i.lower()}@example.com", phone=None) for i in cust_ids])

        insert(c, "product", [dict(id=p["id"], seller_id=p["seller_id"], category=p["category"], name=p["name"],
                                   description=p.get("description"), attributes=json.dumps(p.get("attributes", {})),
                                   listing_image_urls=[f"{storage.scheme}{storage_path(u)}" for u in p["listing_image_urls"]])
                              for p in d["products"]])

        c.execute(text("""INSERT INTO orders (id, customer_id, product_id, variant, batch_id, price, order_date)
                          VALUES (:id, :customer_id, :product_id, CAST(:variant AS jsonb), :batch_id, :price, :order_date)"""),
                  [dict(o, variant=json.dumps(o["variant"])) for o in d["orders"]])
        insert(c, "shipment", [dict(id=s["id"], order_id=s["order_id"], warehouse=s["warehouse"],
                                    delivered_date=s["delivered_date"], damage_flag=s.get("damage_flag", False))
                               for s in d["shipments"]])

        # ── choose the hold-out returns ──
        by_cause: dict[str, list] = {}
        for r in sorted(d["returns"], key=lambda r: r["created_at"], reverse=True):
            by_cause.setdefault(r["stated_reason"], []).append(r["id"])
        holdout = {rid for cause, n in HOLDOUT.items() for rid in by_cause.get(cause, [])[:n]}

        insert(c, "returns", [dict(id=r["id"], order_id=r["order_id"], product_id=r["product_id"],
                                   customer_id=r["customer_id"], stated_reason=r["stated_reason"], comment=r.get("comment"),
                                   status="pending_analysis" if r["id"] in holdout else "reviewed",
                                   created_at=r["created_at"], status_updated_at=r["created_at"]) for r in d["returns"]])

        media_rows = []
        for m in d["return_media"]:
            rel = storage_path(m["storage_url"])
            f = dataset_dir / "mock_storage" / rel
            media_rows.append(dict(id=m["id"], return_id=m["return_id"], type=m["type"], storage_url=f"{storage.scheme}{rel}",
                                   mime_type="image/jpeg" if m["type"] == "photo" else "video/mp4",
                                   size_bytes=f.stat().st_size if f.exists() else None))
        insert(c, "return_media", media_rows)

        # ── synthetic analysis + pre-computed findings + reviews for the reviewed returns ──
        reviewed = [r for r in d["returns"] if r["id"] not in holdout]
        reviews = {r["return_id"]: r for r in d["return_reviews"]}
        findings = {f["return_id"]: f for f in d["media_findings"]}
        media_of = {m["return_id"]: m["id"] for m in d["return_media"]}
        aids = alloc(c, "analysis_seq", "ra_", len(reviewed))
        an_rows, mf_rows, rv_rows = [], [], []
        for r, aid in zip(reviewed, aids):
            rid, rev, f = r["id"], reviews[r["id"]], findings.get(r["id"])
            cause = rev["final_root_cause"]
            created = r["created_at"]
            an_rows.append(dict(id=aid, return_id=rid, root_cause=cause, reason_mismatch=r["stated_reason"] != cause,
                                confidence=0.90,
                                explanation="Imported from dataset v1.1 (pre-labeled). Not produced by the Return Agent.",
                                evidence=json.dumps([{"ref": media_of[rid], "finding": f["description"]}] if f else []),
                                context_notes=json.dumps([]), recommended_action="approve_return",
                                needs_manual_review=False, model_version="dataset-v1.1", created_at=created))
            if f:
                mf_rows.append(dict(id=f["id"], analysis_id=aid, return_id=rid, media_id=f["media_id"],
                                    defect_type=None if f["defect_type"] in (None, "none") else f["defect_type"],
                                    severity=f["severity"], visible_damage=f["visible_damage"],
                                    matches_listing=f["matches_listing"], description=f.get("description") or "",
                                    created_at=created))
            rv_rows.append(dict(return_id=rid, analysis_id=aid, decision=DECISION_MAP[rev["decision"]],
                                final_root_cause=cause, note=rev.get("note"), reviewer=rev.get("reviewer") or "dataset",
                                reviewed_at=rev["reviewed_at"]))
        c.execute(text("""INSERT INTO return_analysis (id, return_id, root_cause, reason_mismatch, confidence, explanation, evidence,
                          context_notes, recommended_action, needs_manual_review, model_version, created_at)
                          VALUES (:id, :return_id, CAST(:root_cause AS root_cause), :reason_mismatch, :confidence, :explanation,
                          CAST(:evidence AS jsonb), CAST(:context_notes AS jsonb), CAST(:recommended_action AS recommended_action),
                          :needs_manual_review, :model_version, :created_at)"""), an_rows)
        c.execute(text("""INSERT INTO media_finding (id, analysis_id, return_id, media_id, defect_type, severity, visible_damage,
                          matches_listing, description, created_at)
                          VALUES (:id, :analysis_id, :return_id, :media_id, :defect_type, CAST(:severity AS severity_level),
                          :visible_damage, :matches_listing, :description, :created_at)"""), mf_rows)
        c.execute(text("""INSERT INTO return_review (return_id, analysis_id, decision, final_root_cause, note, reviewer, reviewed_at)
                          VALUES (:return_id, :analysis_id, CAST(:decision AS review_decision), CAST(:final_root_cause AS root_cause),
                          :note, :reviewer, :reviewed_at)"""), rv_rows)

        # ground truth for every return, including the hold-out
        labels = [dict(id=i, subject_type="return", subject_id=r["return_id"], true_root_cause=r["final_root_cause"],
                       scenario="holdout" if r["return_id"] in holdout else None)
                  for r, i in zip(d["return_reviews"], alloc(c, "eval_seq", "ev_", len(d["return_reviews"])))]
        c.execute(text("""INSERT INTO eval_label (id, subject_type, subject_id, true_root_cause, scenario)
                          VALUES (:id, :subject_type, :subject_id, CAST(:true_root_cause AS root_cause), :scenario)"""), labels)

        # the dataset uses r_101..r_271; make new returns from the API start well above them
        c.execute(text("SELECT setval('returns_seq', 1000)"))

    if copy_images:
        src = dataset_dir / "mock_storage"
        shutil.copytree(src, storage.root, dirs_exist_ok=True)
    print(f"loaded: {len(d['products'])} products, {len(d['orders'])} orders, {len(d['returns'])} returns "
          f"({len(holdout)} held out as pending_analysis, {len(reviewed)} reviewed), {len(cust_ids)} customers, "
          f"{len(d['return_media'])} media rows; images copied to {storage.root}" if copy_images else "loaded (images not copied)")
    print("held out:", ", ".join(sorted(holdout)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="folder holding returniq_deepfashion_dataset.json and mock_storage/")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--profiles-only", action="store_true", help="only add the extra category profiles to the existing database")
    a = ap.parse_args()
    if a.profiles_only:
        with create_engine(settings.app_url).begin() as conn:
            print(f"added {add_extra_profiles(conn)} category profile(s)")
        raise SystemExit
    load(a.dir, copy_images=not a.no_images)
