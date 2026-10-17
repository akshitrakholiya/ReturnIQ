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
│  Customer   │     │  /products/*         Flow B endpoints            │
│  Reviewer   │     │  /media/*            Upload/serve media          │
│  Seller     │     │  /demo/*             Dev helpers                 │
└─────────────┘     └────────┬──────────────────────┬──────────────────┘
                             │                      │
                    ┌────────▼────────┐    ┌────────▼────────┐
                    │  Services       │    │  Agents (ADK)   │
                    │  analysis.py    │    │  return_agent   │
                    │  flow_b/        │    │  rca_agent      │
                    │   pipeline.py   │    │  solution_agent │
                    │   evidence_pack │    │  qa_agent       │
                    │   scoring.py    │    │  stub_model     │
                    └────────┬────────┘    └────────┬────────┘
                             │                      │
                    ┌────────▼──────────────────────▼────────┐
                    │  Tools (read-only, parameterized SQL)   │
                    │  order_shipment · product_catalog       │
                    │  multimodal · policy · flow_b_tools     │
                    └────────────────┬───────────────────────┘
                                     │
                    ┌────────────────▼───────────────────────┐
                    │  PostgreSQL / AlloyDB                   │
                    │  schema.sql (Flow A) + flow_b_schema   │
                    │  18 tables · 4 views · read-only role   │
                    └────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Database
cd server
python -m scripts.init_db --reset    # creates tables, roles, seeds
# or apply manually: psql < db/schema.sql && psql < db/flow_b_schema.sql

# 2. Server
cp .env.example .env                 # edit DB creds, LLM_MODE=stub for testing
pip install -r requirements.txt
uvicorn app.main:app --reload

# 3. Frontend
cd ../web
npm install && npm run dev           # http://localhost:5173
```

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

| Method | Path | Flow |
|--------|------|------|
| POST | `/returns` | A — submit a return |
| GET | `/returns/{id}` | A — return detail + verdict |
| POST | `/returns/{id}/review` | A — human decision |
| GET | `/products` | B — seller's product list |
| POST | `/products/{id}/report` | B — trigger report build |
| GET | `/products/{id}/report` | B — poll / get report |
| POST | `/products/{id}/questions` | B — ask Q&A |

## Project Rules

See [docs/PROJECT_RULES.md](docs/PROJECT_RULES.md).