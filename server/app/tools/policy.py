"""Policy toolset (Flow A). Plain Postgres full-text search; enough for a few policy docs."""
import logging

from app.tools._db import query

log = logging.getLogger(__name__)

_SQL = """SELECT id, section, title, text, ts_rank(tsv, t.q) AS rank
          FROM policy CROSS JOIN LATERAL (SELECT {expr} AS q) t
          WHERE tsv @@ t.q ORDER BY rank DESC, section LIMIT 3"""
_AND = "websearch_to_tsquery('english', :t)"
_OR = "replace(plainto_tsquery('english', :t)::text, '&', '|')::tsquery"  # relax AND to OR


def search_policy(query_text: str) -> dict:
    """Find the return-policy sections that match a topic, e.g. 'defective items' or
    'damaged in transit'. Returns the top 3 sections with id, section, title and text.
    Cite the returned id (like 'policy_2.1') as evidence."""
    try:
        rows = query(_SQL.format(expr=_AND), t=query_text) or query(_SQL.format(expr=_OR), t=query_text)
    except Exception as e:  # a tool failure must not look like a model failure; let the agent carry on
        log.exception("search_policy failed")
        return {"query": query_text, "sections": [], "error": f"policy search unavailable: {type(e).__name__}"}
    return {"query": query_text, "sections": [{k: v for k, v in r.items() if k != "rank"} for r in rows]}
