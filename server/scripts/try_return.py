"""Try Flow A as a customer: upload images, submit a return, wait for the AI verdict, print it.

    python -m scripts.try_return --product "TrailRun Sneakers" --reason size_fit \
        --comment "The sole came off after two days" photo1.jpg photo2.jpg
    python -m scripts.try_return --order o_2822 --reason defect_quality     # no media

Needs the API running: uvicorn app.main:app --reload
"""
import argparse
import json
import mimetypes
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import text

from app.db.session import engine

BASE = "http://localhost:8000"


def free_order(product: str) -> str:
    with engine.connect() as c:
        oid = c.execute(text("""SELECT o.id FROM orders o JOIN product p ON p.id = o.product_id
                                LEFT JOIN returns r ON r.order_id = o.id
                                WHERE r.id IS NULL AND p.name = :n ORDER BY o.order_date DESC LIMIT 1"""),
                        {"n": product}).scalar()
    if not oid:
        sys.exit(f"No order without a return found for product '{product}'")
    return oid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", help="order id like o_2822 (must not have a return yet)")
    ap.add_argument("--product", default="TrailRun Sneakers", help="used to pick a free order when --order is not given")
    ap.add_argument("--reason", default="size_fit")
    ap.add_argument("--comment", default=None)
    ap.add_argument("images", nargs="*", help="photo/video files (jpg, png, webp, mp4, mov)")
    a = ap.parse_args()

    with httpx.Client(base_url=BASE, timeout=120) as http:
        media = []
        for path in a.images:
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            r = http.post("/media/upload-url", json={"content_type": ctype}); r.raise_for_status()
            j = r.json()
            put = http.put(j["upload_url"], content=Path(path).read_bytes(), headers={"content-type": ctype})
            put.raise_for_status()
            media.append({"storage_url": j["storage_url"]})
            print(f"uploaded {path} -> {j['storage_url']}")

        order = a.order or free_order(a.product)
        r = http.post("/returns", json={"order_id": order, "stated_reason": a.reason,
                                        "comment": a.comment, "media": media})
        if r.status_code != 201:
            sys.exit(f"POST /returns failed: {r.status_code} {r.text}")
        rid = r.json()["return_id"]
        print(f"\ncreated {rid} for order {order}; waiting for the AI ...")

        t0 = time.time()
        while True:
            d = http.get(f"/returns/{rid}").json()
            if d["status"] in ("awaiting_review", "analysis_failed", "reviewed"):
                break
            if time.time() - t0 > 120:
                sys.exit(f"timed out; status is still {d['status']}")
            time.sleep(2)
        print(f"status: {d['status']} ({time.time() - t0:.0f}s)\n")
        print(f"product: {d['product_name']} | variant {d['variant']} | batch {d['batch_id']}")
        print(f"customer said: {d['stated_reason']} - {d['comment']}")
        if d["analysis"]:
            an = d["analysis"]
            print(f"\nAI verdict: {an['root_cause']} (confidence {an['confidence']}, mismatch={an['reason_mismatch']})")
            print(f"action: {an['recommended_action']} | manual review: {an['needs_manual_review']}")
            print(f"why: {an['explanation']}")
            print("evidence:"); [print(f"  - {e['ref']}: {e['finding']}") for e in an["evidence"]]
            print("media findings:"); [print(f"  - {f['media_id']}: {f['defect_type']} / {f['severity']} / {f['description']}") for f in d["media_findings"]]
            print("notes:", an["context_notes"])
        print(f"\nNext: review it in http://localhost:8000/docs  ->  POST /returns/{rid}/review")


if __name__ == "__main__":
    main()
