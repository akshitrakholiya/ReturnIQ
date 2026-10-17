"""Convert stored media references from 'local://<path>' to the plain media path '<path>'.

The database now stores only the path inside the storage (see app/services/storage.py). Run this once
on a database created before that change. Safe to run again: it only touches values that still have
the old prefix, and reports what it changed.
    python -m scripts.migrate_media_paths
"""
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.services.storage import LEGACY_PREFIX

# JSON columns that can carry copies of media references (traces, evidence, reports)
JSON_COLUMNS = [("return_analysis", "evidence"), ("agent_run", "tool_calls"), ("agent_run", "raw_output"),
                ("evidence_pack", "items"), ("product_report", "report"), ("product_qa", "answer"),
                ("product_qa", "tool_calls")]


def migrate() -> None:
    p = LEGACY_PREFIX
    with create_engine(settings.app_url).begin() as db:
        exists = lambda t: db.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{t}"}).scalar() is not None  # noqa: E731
        changed = {
            "return_media.storage_url": db.execute(text(
                "UPDATE return_media SET storage_url = substr(storage_url, :n) WHERE storage_url LIKE :like"),
                {"n": len(p) + 1, "like": p + "%"}).rowcount,
            "product.listing_image_urls": db.execute(text("""
                UPDATE product SET listing_image_urls = ARRAY(
                  SELECT CASE WHEN u LIKE :like THEN substr(u, :n) ELSE u END
                  FROM unnest(listing_image_urls) WITH ORDINALITY AS t(u, ord) ORDER BY ord)
                WHERE array_to_string(listing_image_urls, ',') LIKE :any"""),
                {"n": len(p) + 1, "like": p + "%", "any": "%" + p + "%"}).rowcount,
        }
        for table, col in JSON_COLUMNS:
            if exists(table):
                changed[f"{table}.{col}"] = db.execute(text(
                    f"UPDATE {table} SET {col} = replace({col}::text, :p, '')::jsonb WHERE {col}::text LIKE :any"),
                    {"p": p, "any": "%" + p + "%"}).rowcount
    done = {k: v for k, v in changed.items() if v}
    print("media references migrated: " + (", ".join(f"{k} {v}" for k, v in done.items()) if done else "nothing to change"))


if __name__ == "__main__":
    migrate()
