"""Flow A checks: plain code that validates and corrects the agent's verdict before it is saved."""
import json
import re

from app.core.config import settings
from app.schemas.verdict import ReturnVerdict

_NUM = re.compile(r"\d+(?:\.\d+)?")


def numbers_in(s: str) -> set[str]:
    return set(_NUM.findall(s))


def policy_ids(tool_results: list[dict]) -> set[str]:
    out = set()
    for tr in tool_results:
        if tr["name"] == "search_policy":
            out |= {s["id"] for s in tr["response"].get("sections", [])}
    return out


def wrong_numbers(verdict: ReturnVerdict, context: dict, tool_results: list[dict]) -> list[str]:
    """Numbers the agent wrote that appear nowhere in the context or tool results."""
    allowed = numbers_in(json.dumps(context, default=str) + json.dumps(tool_results, default=str))
    written = numbers_in(verdict.explanation + " " + " ".join(e.finding for e in verdict.evidence))
    return sorted(written - allowed)


def check_verdict(verdict: ReturnVerdict, context: dict, tool_results: list[dict]) -> tuple[dict, list[str]]:
    """Returns (verdict dict ready to save, list of corrections made)."""
    v = verdict.model_dump()
    fixes: list[str] = []

    # 1. facts the code already knows are not the model's to decide
    stated = context["return"]["stated_reason"]
    if v["stated_reason"] != stated:
        fixes.append(f"stated_reason corrected to '{stated}'")
    v["stated_reason"] = stated
    v["reason_mismatch"] = stated != v["root_cause"]

    # 2. citation check: every evidence ref must be an ID we actually gave or the tools returned
    allowed = set(context["known_refs"]) | policy_ids(tool_results)
    kept = [e for e in v["evidence"] if e["ref"] in allowed]
    if len(kept) != len(v["evidence"]):
        fixes.append(f"dropped {len(v['evidence']) - len(kept)} evidence item(s) with unknown refs")
    v["evidence"] = kept

    # 3. number check (a final pass: anything still wrong after the retry is removed)
    bad = set(wrong_numbers(verdict, context, tool_results))
    if bad:
        kept = [e for e in v["evidence"] if not (numbers_in(e["finding"]) & bad)]
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", v["explanation"]) if not (numbers_in(s) & bad)]
        v["evidence"] = kept
        v["explanation"] = " ".join(sentences) or "Explanation removed: its numbers could not be verified."
        fixes.append(f"removed text with unverified numbers: {sorted(bad)}")

    # 4. forced manual review
    force = False
    if v["confidence"] < settings.manual_review_confidence:
        force = True
    if not context["media"]:
        force = True
        v["evidence"].append({"ref": context["return"]["id"], "finding": "media unavailable"})
        fixes.append("no media: forced manual review")
    else:
        # media was uploaded but the vision step failed or skipped files: the verdict rests on text alone
        analyzed = {f.get("media_id") for tr in tool_results if tr["name"] == "analyze_media"
                    for f in tr["response"].get("findings", []) if f.get("analyzed", True)}
        missing = [m["id"] for m in context["media"] if m["id"] not in analyzed]
        if missing:
            force = True
            v["evidence"].append({"ref": context["return"]["id"],
                                  "finding": f"photo analysis unavailable for {', '.join(missing)}"})
            fixes.append(f"media not analyzed ({', '.join(missing)}): forced manual review")
    if not v["evidence"]:
        force = True
        fixes.append("no valid evidence left: forced manual review")
    if force and not v["needs_manual_review"]:
        fixes.append("needs_manual_review forced to true")
    if force:
        v["needs_manual_review"] = True
        v["recommended_action"] = "manual_review"
    v["confidence"] = round(v["confidence"], 2)
    return v, fixes
