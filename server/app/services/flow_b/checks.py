"""Flow B checks (code): citation check and number check, shared by the report and Q&A.

Citation check: every evidence ref must be an ID from the evidence pack or a tool result of that run.
Number check: every number an agent writes must appear in the pack or that run's tool results
(a share like 0.604 may be written as 60 or 60.4). Thresholds from the instructions are allowed too.
"""
import json
import re

from app.core.config import settings
from app.schemas.flow_b import EvidencePack, EvidenceRef, ToolResult
from app.services.flow_b.evidence_pack import pack_refs

_NUM = re.compile(r"\d+(?:\.\d+)?")
_IDS = re.compile(r"\b(?:r|lc|m)_\d+\b")


def canon(n: str | float) -> str:
    return ("%.4f" % float(n)).rstrip("0").rstrip(".")


def numbers_in(s: str) -> set[str]:
    return {canon(n) for n in _NUM.findall(s or "")}


def allowed_numbers(*sources) -> set[str]:
    nums = set()
    for s in sources:
        nums |= numbers_in(s if isinstance(s, str) else json.dumps(s, default=str))
    for n in list(nums):  # 0.604 may be written as 60% or 60.4%
        f = float(n)
        if 0 < f <= 1:
            nums |= {canon(round(f * 100)), canon(round(f * 100, 1))}
    return nums | {canon(settings.rca_min_returns), canon(round(settings.rca_min_share * 100))}


def evidence_numbers(pack: EvidencePack, tool_results: list[ToolResult], *extra) -> set[str]:
    return allowed_numbers(pack.model_dump(mode="json"), [t.model_dump(mode="json") for t in tool_results], *extra)


def tool_refs(tool_results: list[ToolResult]) -> set[str]:
    """ref_ids plus the return / listing change / media IDs that appear inside tool results."""
    refs = {t.ref_id for t in tool_results}
    for t in tool_results:
        refs |= set(_IDS.findall(json.dumps(t.data, default=str)))
    return refs


def known_refs(pack: EvidencePack, tool_results: list[ToolResult]) -> set[str]:
    return pack_refs(pack) | tool_refs(tool_results)


def wrong_numbers(texts: list[str], allowed: set[str]) -> list[str]:
    written = set().union(*(numbers_in(t) for t in texts)) if texts else set()
    return sorted(written - allowed, key=float)


def keep_cited(items: list[EvidenceRef], refs: set[str]) -> tuple[list[EvidenceRef], list[str]]:
    kept = [e for e in items if e.ref in refs]
    return kept, [e.ref for e in items if e.ref not in refs]


def keep_numbers(items: list[EvidenceRef], allowed: set[str]) -> tuple[list[EvidenceRef], list[str]]:
    kept = [e for e in items if numbers_in(e.finding) <= allowed]
    bad = sorted(set().union(*(numbers_in(e.finding) - allowed for e in items)) if items else set())
    return kept, bad


def strip_sentences(text: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Drop the sentences whose numbers cannot be verified."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [s for s in parts if numbers_in(s) <= allowed]
    bad = sorted(set().union(*(numbers_in(s) - allowed for s in parts)) if parts else set())
    return " ".join(kept), bad
