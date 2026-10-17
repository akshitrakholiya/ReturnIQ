from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import demo, media, returns
from app.db.session import engine

app = FastAPI(title="ReturnIQ API")
app.add_middleware(  # the React dev server (Vite) runs on another port
    CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"])
app.include_router(demo.router)
app.include_router(media.router)
app.include_router(returns.router)


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
