"""Evaluate Flow B against the planted ground truth (eval_label, subject_type='product').

Builds a fresh report for every labelled product (runs the full pipeline in-process) and checks
that the top-ranked root cause is the planted one, then that unlabelled products show no false alarm.
    python -m scripts.eval_flow_b              # uses LLM_MODE from .env
    LLM_MODE=stub python -m scripts.eval_flow_b
"""
import sys

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.flow_b.pipeline import run_report, run_status, start_run


def build(product_id: str):
    with SessionLocal() as db:
        run, _ = start_run(db, product_id)
    run_report(run["id"], product_id)
    with SessionLocal() as db:
        return run_status(db, product_id, run["id"])


def main() -> int:
    with SessionLocal() as db:
        labels = db.execute(text("""SELECT subject_id, true_root_cause::text AS cause, scenario FROM eval_label
                                    WHERE subject_type = 'product' ORDER BY subject_id""")).mappings().all()
        others = db.execute(text("""SELECT id FROM product WHERE id <> ALL(:ids) ORDER BY id"""),
                            {"ids": [l["subject_id"] for l in labels]}).scalars().all()
    if not labels:
        print("no product labels; run python -m scripts.plant_flow_b first")
        return 1
    hits = 0
    for l in labels:
        r = build(l["subject_id"])
        top = r.report.root_causes[0] if r.report and r.report.root_causes else None
        ok = top is not None and top.cause.value == l["cause"]
        hits += ok
        print(f"{'PASS' if ok else 'FAIL'} {l['subject_id']:5} {l['scenario']:24} expected {l['cause']:18} "
              f"got {top.cause.value if top else (r.run.error or 'no root cause')}"
              + (f" (confidence {top.confidence.score}, fix: {'yes' if top.fix else 'no'})" if top else ""))
    alarms = []
    for pid in others:
        r = build(pid)
        if r.report and r.report.root_causes:
            alarms.append(f"{pid}: {', '.join(c.cause.value for c in r.report.root_causes)}")
    print(f"\nplanted scenarios found: {hits}/{len(labels)}")
    print(f"root causes on unlabelled products: {len(alarms)}/{len(others)}" + "".join(f"\n  {a}" for a in alarms))
    return 0 if hits == len(labels) else 1


if __name__ == "__main__":
    sys.exit(main())
