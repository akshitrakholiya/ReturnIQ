from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Read/write engine: only the API writes to the DB.
engine = create_engine(settings.app_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

# Read-only engine: the agent tool layer uses this one (statement timeout 60 s).
tools_engine = create_engine(
    settings.tools_url,
    pool_pre_ping=True,
    connect_args={"options": "-c statement_timeout=60000 -c default_transaction_read_only=on"},
)


def get_session():
    with SessionLocal() as session:
        yield session


__all__ = ["engine", "tools_engine", "SessionLocal", "Session", "get_session"]
