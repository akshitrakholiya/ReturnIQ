# ReturnIQ server

FastAPI backend: the Flow A and Flow B APIs, the agents (Google ADK + Gemini: Return, RCA, Solution, Q&A), the read-only tools, the database schema and the data scripts.

```bash
cd server
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                   # set GOOGLE_API_KEY, or LLM_MODE=stub
python -m scripts.init_db --reset      # roles, database, tables (Flow A + Flow B)
python -m scripts.load_dataset         # dataset from ../docs/DataSet v1.1
python -m scripts.seed_flow_b          # cost model per category + sample listing changes
python -m scripts.plant_flow_b         # previous-period history + 4 planted Flow B scenarios; prints REPORT_AS_OF
uvicorn app.main:app --reload          # http://localhost:8000  (Swagger: /docs)
```

Run every command from inside `server/`. Full instructions, the web app and troubleshooting are in the [root README](../README.md).

## Flow B (product reports + seller Q&A)

| Step | Code | |
|---|---|---|
| 1-2 Cache + health check | `app/services/flow_b/health.py` | code |
| 3 Evidence pack | `app/services/flow_b/evidence_pack.py` | code |
| 4-5 RCA + Solution agents | `app/agents/flow_b_agents.py`, `runner.py`, `stub_flow_b.py` | Gemini (or stub) |
| 6 Checks + scoring | `app/services/flow_b/checks.py`, `scoring.py` | code |
| 7 Run + save | `app/services/flow_b/pipeline.py` | code |
| Q&A | `app/services/flow_b/qa.py` | Gemini (or stub) |
| Tools | `app/tools/product_intelligence.py`, `product_catalog.get_listing_changes` | read-only SQL |

Endpoints: `GET /sellers`, `GET /sellers/{id}/products`, `GET /products/{id}/report` (fresh report, or starts a run),
`GET /products/{id}/report/runs/{run_id}` (poll), `POST /products/{id}/report/refresh`,
`POST /products/{id}/questions`, `GET /products/{id}/questions?session_id=`, `GET /products/{id}/evidence-packs/{pack_id}`.

`REPORT_AS_OF` pins the end of the 90-day window so the demo data never ages out; `python -m scripts.eval_flow_b`
checks that every planted scenario is found and that no other product gets a false root cause.
