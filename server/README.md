# ReturnIQ server

FastAPI backend: the Flow A API, the Return Agent (Google ADK + Gemini), the read-only tools, the database schema and the data scripts.

```bash
cd server
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                   # set GOOGLE_API_KEY, or LLM_MODE=stub
python -m scripts.init_db --reset      # roles, database, tables
python -m scripts.load_dataset         # dataset from ../docs/DataSet v1.1
uvicorn app.main:app --reload          # http://localhost:8000  (Swagger: /docs)
```

Run every command from inside `server/`. Full instructions, the web app and troubleshooting are in the [root README](../README.md).
