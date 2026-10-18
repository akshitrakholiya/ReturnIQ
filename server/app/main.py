from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import demo, media, products, returns
from app.db.session import engine
from app.services.analysis import expire_stuck_analyses


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Analyses run as in-process background tasks, so a restart (incl. uvicorn --reload) kills them.
    # Assumes one server process: with several workers, a starting worker would fail the others' live runs.
    expire_stuck_analyses(all_running=True)
    yield


app = FastAPI(title="ReturnIQ API", lifespan=lifespan)
app.add_middleware(  # the React dev server (Vite) runs on another port
    CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"])
app.include_router(demo.router)
app.include_router(media.router)
app.include_router(returns.router)
app.include_router(products.router)


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
