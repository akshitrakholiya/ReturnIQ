# ReturnIQ — FastAPI Service & API Architecture Skill

## Core Objective
Enforce the asynchronous architecture, background polling lifecycle, and boundary isolation for ReturnIQ's FastAPI service[cite: 4, 5, 8].

## Architectural Rules
1. **Background Tasks for Long-Running Agents:**
   - Single return analysis (Flow A) and Product Report runs (Flow B) take between 15 to 45 seconds[cite: 8]. Never block the HTTP request thread[cite: 8].
   - Dispatch reasoning workflows via FastAPI `BackgroundTasks`[cite: 5, 8].
   - Flow B runs must update the `report_run` table through discrete lifecycle states: `gathering` -> `finding_causes` -> `preparing_fixes` -> `done` (or `failed`)[cite: 2, 8, 18].
   - Provide polling endpoints (`GET /products/{id}/report/runs/{run_id}`) designed for client polling every 2–3 seconds[cite: 8, 17].

2. **Strict DB Write Boundary:**
   - Plain code inside the API routes writes to persistent storage (AlloyDB / PostgreSQL)[cite: 4, 5].
   - Reasoning agents (Google ADK) NEVER write directly to the database; their outputs return to the API layer, which validates, scores, and persists them[cite: 4, 5].

3. **Required Route Endpoints:**
   - **Flow A:** `POST /media/upload-url`, `POST /returns`, `GET /returns?status=awaiting_review`, `GET /returns/{id}`, `POST /returns/{id}/reanalyze`, `POST /returns/{id}/review`[cite: 16].
   - **Flow B:** `GET /sellers`, `GET /sellers/{id}/products`, `GET /products/{id}/report`, `GET /products/{id}/report/runs/{run_id}`, `POST /products/{id}/report/refresh`, `GET /products/{id}/evidence-packs/{pack_id}`, `POST /products/{id}/questions`, `GET /products/{id}/questions?session_id=`[cite: 16, 17].

4. **Reviewer Invalidation Hook:**
   - When `POST /returns/{id}/review` completes, mark `product.report_stale = true` for that product to flag the report for rebuilding[cite: 6, 17, 19].