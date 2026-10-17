"""Run the Return Agent on pending returns and score it against eval_label (the dataset's true causes).

    python -m scripts.eval_flow_a --limit 5                  # first 5 pending returns
    python -m scripts.eval_flow_a --ids r_112 r_128          # specific returns
    python -m scripts.eval_flow_a --limit 17 --pause 20      # all held-out ones, 20 s between runs (free-tier quotas)

Each run goes through the real job (context -> agent -> checks -> save), so the returns end up in
`awaiting_review` with a real analysis. Reload the dataset (init_db --reset + load_dataset) to start over.
"""
import argparse
import asyncio
import time
from collections import Counter

from sqlalchemy import text

from app.db.session import engine
from app.services.analysis import run_return_analysis


def pending(limit: int, ids: list[str] | None) -> list[str]:
    with engine.connect() as c:
        if ids:
            return ids
        return [r[0] for r in c.execute(text("""SELECT id FROM returns WHERE status = 'pending_analysis'
                                                ORDER BY created_at DESC LIMIT :n"""), {"n": limit})]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--pause", type=float, default=0, help="seconds to wait between returns")
    a = ap.parse_args()

    rows = []
    for i, rid in enumerate(pending(a.limit, a.ids)):
        if i and a.pause:
            time.sleep(a.pause)
        t0 = time.time()
        run_return_analysis(rid)
        secs = time.time() - t0
        with engine.connect() as c:
            r = c.execute(text("""
                SELECT r.status, r.stated_reason::text, l.true_root_cause::text truth, ra.root_cause::text ai, ra.confidence,
                       ra.needs_manual_review, ra.reason_mismatch, ar.model, mf.defect_type, mf.severity::text, mf.matches_listing
                FROM returns r
                LEFT JOIN eval_label l ON l.subject_type = 'return' AND l.subject_id = r.id
                LEFT JOIN return_analysis ra ON ra.return_id = r.id AND ra.is_current
                LEFT JOIN agent_run ar ON ar.id = ra.agent_run_id
                LEFT JOIN media_finding mf ON mf.analysis_id = ra.id
                WHERE r.id = :id LIMIT 1"""), {"id": rid}).mappings().first()
        rows.append(dict(r) | {"id": rid, "secs": secs})
        mark = "OK " if r["ai"] == r["truth"] else ("-- " if r["ai"] else "ERR")
        print(f"{mark} {rid:6} truth={r['truth']:18} stated={r['stated_reason']:18} ai={str(r['ai']):18} "
              f"conf={r['confidence']} manual={r['needs_manual_review']} {secs:4.0f}s {r['model']} | "
              f"{r['defect_type']}/{r['severity']}/match={r['matches_listing']}", flush=True)

    done = [r for r in rows if r["ai"]]
    if not rows:
        print("nothing to evaluate"); return
    correct = sum(r["ai"] == r["truth"] for r in done)
    print(f"\nanalyzed {len(done)}/{len(rows)} | correct {correct}/{len(done)} ({100 * correct / max(len(done), 1):.0f}%) "
          f"| failed {len(rows) - len(done)} | manual review {sum(bool(r['needs_manual_review']) for r in done)} "
          f"| avg {sum(r['secs'] for r in rows) / len(rows):.0f}s")
    wrong = Counter((r["truth"], r["ai"]) for r in done if r["ai"] != r["truth"])
    if wrong:
        print("confusions (truth -> ai):", dict(wrong))
    print("by truth:", {t: f"{sum(r['ai'] == t for r in done if r['truth'] == t)}/{sum(r['truth'] == t for r in done)}"
                        for t in sorted({r['truth'] for r in done})})


if __name__ == "__main__":
    main()
