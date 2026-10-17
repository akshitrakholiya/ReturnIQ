# ReturnIQ — AI-Powered E-Commerce Return Intelligence

ReturnIQ analyzes e-commerce returns at two levels:
- **Flow A (Per-Return):** Multimodal AI analyzes each return, verifies customer claims against evidence, and recommends an action for human review.
- **Flow B (Product-Level RCA):** Aggregates return patterns per product, isolates root causes with strict evidence citations, computes financial impact, proposes actionable fixes, and powers interactive seller Q&A.

Built with **Google ADK + Gemini**, **FastAPI**, **PostgreSQL/AlloyDB**, and **React + Vite**.

## Architecture

```text
┌─────────────┐     ┌──────────────────────────────────────────────────┐
│  React SPA  │────▸│  FastAPI (app/main.py)                          │
│  (web/)     │◂────│                                                  │
│             │     │  /returns/*          Flow A endpoints            │
│  Customer   │     │  /sellers, /products Flow B endpoints            │
│  Reviewer   │     │  /media/*            Upload/serve media          │
│  Seller     │     │  /demo/*             Dev helpers                 │
└─────────────┘     └────────┬──────────────────────┬──────────────────┘
                             │                      │
                    ┌────────▼────────┐    ┌────────▼────────┐
                    │  Services       │    │  Agents (ADK)   │
                    │  analysis.py    │    │  return_agent   │
                    │  flow_b/        │    │  flow_b_agents  │
                    │   pipeline.py   │    │   rca·solution  │
                    │   evidence_pack │    │   ·qa · runner  │
                    │   scoring.py    │    │  stub models    │
                    └────────┬────────┘    └────────┬────────┘
                             │                      │
                    ┌────────▼──────────────────────▼────────┐
                    │  Tools (read-only, parameterized SQL)   │
                    │  order_shipment · product_catalog       │
                    │  multimodal · policy · product_intel.   │
                    └────────────────┬───────────────────────┘
                                     │
                    ┌────────────────▼───────────────────────┐
                    │  PostgreSQL / AlloyDB                   │
                    │  schema.sql (Flow A) + flow_b_schema   │
                    │  20 tables · 4 views · read-only role   │
                    └────────────────────────────────────────┘
```

## Quick Start

Needs Docker, Python 3.13 and Node 22. Run the server commands from `server/`.

```bash
# 1. Postgres
docker run -d --name returniq-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16

# 2. Server setup
cd server
python -m venv .venv && .venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # add GOOGLE_API_KEY, or keep LLM_MODE=stub (no AI calls)
python -m scripts.init_db --reset    # roles, database, empty tables (Flow A + Flow B)
```

3. Load data (not in git), with **either** option:

   - **A. Restore the shared demo database (recommended).** Ask the team for the `returniq_share` folder and follow its
     `RESTORE.md`, or the short version in [server/README.md](server/README.md#quicker-restore-the-shared-demo-database).
   - **B. Build it from the dataset folder (`DataSet v1.1`):**
     ```bash
     python -m scripts.load_dataset --dir "path/to/DataSet v1.1"   # 20 apparel products + photos
     python -m scripts.add_category_data                            # 6 footwear / electronics products
     python -m scripts.seed_flow_b                                  # cost model + listing changes
     python -m scripts.plant_flow_b                                 # previous-period history + 4 demo scenarios
     ```
   - No data at hand? `python -m scripts.init_db --reset --seed` loads synthetic data instead.

```bash
# 4. Run
uvicorn app.main:app --reload             # http://localhost:8000/docs
cd ../web && npm install && npm run dev   # http://localhost:5173
```

Keep `REPORT_AS_OF=2026-10-16` in `.env` (it is in `.env.example`) so the demo data stays inside the 90-day report window.
`python -m scripts.eval_flow_b` checks that Flow B finds every planted scenario.

## Flow B Pipeline

| Step | Type | What Happens |
|------|------|-------------|
| 1. Cache check | code | Return cached report if fresh, else continue |
| 2. Health check | code | Skip agents if < 5 returns or rate is healthy |
| 3. Evidence pack | code | Build breakdowns, feedback, listing info |
| 4. RCA Agent | agent | Identify root causes (≥ 5 returns, ≥ 20% share) |
| 5. Solution Agent | agent | Propose a fix per root cause |
| 6. Checks & scoring | code | Validate citations, compute confidence + impact |
| 7. Save & show | code | Persist report, update run status |

## Key Endpoints

Full list with request/response schemas: http://localhost:8000/docs

| Method | Path | Flow |
|--------|------|------|
| POST | `/media/upload-url` | A — signed upload URL for one photo/video |
| POST | `/returns` | A — submit a return (starts the AI analysis) |
| GET | `/returns?status=awaiting_review` | A — reviewer queue |
| GET | `/returns/{id}` | A — return detail + AI verdict |
| POST | `/returns/{id}/review` | A — human decision (marks the product report stale) |
| POST | `/returns/{id}/reanalyze` | A — rerun the analysis |
| GET | `/sellers` | B — sellers (demo switcher) |
| GET | `/sellers/{id}/products` | B — product list with return rate, top cause, report status |
| GET | `/products/{id}/report` | B — saved report if fresh, otherwise starts a run |
| GET | `/products/{id}/report/runs/{run_id}` | B — run progress, and the report when done (poll every 2–3 s) |
| POST | `/products/{id}/report/refresh` | B — force a new analysis |
| GET | `/products/{id}/evidence-packs/{pack_id}` | B — the evidence a report cites |
| POST | `/products/{id}/questions` | B — ask a question (Q&A) |
| GET | `/products/{id}/questions?session_id=` | B — Q&A history |

## Media

The database stores only the path of each image inside the media storage (`returns/P19/r_255/r_255_defect.jpg`);
the server builds the URL when it shows one. Locally the files live in `server/media_uploads/`.
Details: [server/README.md](server/README.md#media-references).

## Project Rules

See `server/docs/PROJECT_RULES.md`. The `docs/` folders are git-ignored, so ask the team for a copy.