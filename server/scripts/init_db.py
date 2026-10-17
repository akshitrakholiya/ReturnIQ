"""Create the local ReturnIQ database, apply db/schema.sql and (optionally) seed it.

    python -m scripts.init_db            # create if missing, apply schema when empty
    python -m scripts.init_db --reset    # drop and recreate the database
    python -m scripts.init_db --seed     # also load demo data (implies empty DB)
"""
import argparse
from pathlib import Path

from sqlalchemy import create_engine, text

from app.core.config import settings

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def ensure_roles_and_db(reset: bool) -> None:
    admin = create_engine(settings.admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        for user, pw in ((settings.db_user, settings.db_password),
                         (settings.tools_db_user, settings.tools_db_password)):
            if not c.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:u"), {"u": user}).scalar():
                c.execute(text(f'CREATE ROLE "{user}" LOGIN PASSWORD :p'.replace(":p", f"'{pw}'")))
        # AlloyDB's admin user is not a true superuser: it must be a member of a role to create a database owned by it
        c.execute(text(f'GRANT "{settings.db_user}" TO CURRENT_USER'))
        if reset:
            c.execute(text(f'DROP DATABASE IF EXISTS "{settings.db_name}" WITH (FORCE)'))
        if not c.execute(text("SELECT 1 FROM pg_database WHERE datname=:d"), {"d": settings.db_name}).scalar():
            c.execute(text(f'CREATE DATABASE "{settings.db_name}" OWNER "{settings.db_user}"'))
            print(f"created database {settings.db_name}")


def apply_schema() -> bool:
    with create_engine(settings.app_url).begin() as c:
        if c.execute(text("SELECT to_regclass('public.returns')")).scalar():
            print("schema already present (use --reset to rebuild)")
            return False
        c.exec_driver_sql(SCHEMA.read_text().replace("%", "%%"))
        print("schema applied")
        return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--seed", action="store_true")
    args = ap.parse_args()
    ensure_roles_and_db(args.reset)
    fresh = apply_schema()
    if args.seed and fresh:
        from scripts.seed import seed
        seed()
