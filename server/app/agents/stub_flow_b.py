"""Scripted stand-ins for Gemini for the Flow B agents (RCA, Solution, Q&A), plugged into ADK as BaseLlm.

Like the Flow A stub they behave like a model: read the context from the prompt, ask ADK to call a
drill-down tool, then write schema-valid JSON that cites real IDs and copies numbers from the
evidence. Swap to real Gemini with LLM_MODE=gemini; nothing else changes.
"""
import json
import re
from typing import AsyncGenerator

from google.adk.models import BaseLlm
from google.adk.models.base_llm import LlmCapabilities
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from app.agents.stub_model import CONTEXT_MARKER, RETRY_MARKER, _call, _text, _texts

OWNER = {"size_fit": "seller", "defect_quality": "seller", "not_as_described": "seller", "wrong_item": "logistics",
         "damaged_in_transit": "logistics", "changed_mind": "none", "suspicious": "none", "other": "none"}
TITLE = {"size_fit": "Size chart does not match the product for {v}",
         "defect_quality": "Manufacturing defect concentrated in {v}",
         "damaged_in_transit": "Items damaged in transit, mostly from {v}",
         "not_as_described": "Product does not match the listing ({v})",
         "wrong_item": "Wrong items shipped from {v}",
         "changed_mind": "Customers changing their mind", "suspicious": "Suspicious return pattern",
         "other": "Other return reasons"}
# where a concentration would show for each cause, in order of preference
SPLIT = {"size_fit": ["size", "model"], "defect_quality": ["batch"], "damaged_in_transit": ["warehouse"],
         "wrong_item": ["warehouse"], "not_as_described": ["color", "model"]}


def _context(contents) -> dict:
    return json.loads(_texts(contents, "user")[0].split(CONTEXT_MARKER, 1)[1])


def _tool_responses(contents) -> list[dict]:
    return [p.function_response.response for c in contents for p in (c.parts or []) if p.function_response]


class _StubBase(BaseLlm):
    behavior: str = "normal"  # tests: "bad_json_once" (retry path), "bad_json_always" (failure path)

    @classmethod
    def supported_models(cls) -> list[str]:
        return []

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=False)

    def _bad_json(self, contents) -> bool:
        retried = any(RETRY_MARKER in t for t in _texts(contents, "user"))
        return self.behavior == "bad_json_always" or (self.behavior == "bad_json_once" and not retried)


def _rows(breakdown: dict | None) -> list[dict]:
    return [r for r in (breakdown or {}).get("rows", []) if r["count"] > 0
            and r["group"] not in ("not_analyzed", "unknown", "no_photo_finding", "no_issue_visible")]


class StubRcaLlm(_StubBase):
    model: str = "stub-rca-llm"

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        contents = llm_request.contents
        pack = _context(contents)["evidence_pack"]
        bds = {b["id"]: b for b in pack["breakdowns"]}
        causes = [r for r in _rows(bds.get("breakdown:root_cause")) if r["count"] >= 5 and r["share"] >= 0.2]
        responses = _tool_responses(contents)
        # one drill-down: the split for the top cause that the pack did not filter by that cause
        if causes and not responses:
            cause = causes[0]["group"]
            for dim in SPLIT.get(cause, []):
                b = bds.get(f"breakdown:{dim}")
                if b and b["filter"].get("cause") != cause:
                    yield _call("get_return_breakdown", dict(product_id=pack["product_id"], group_by=dim, cause=cause))
                    return
            yield _call("get_return_feedback", dict(product_id=pack["product_id"], cause=cause, limit=5))
            return
        if self._bad_json(contents):
            yield _text("I think it is the size chart.")
            return
        yield _text(json.dumps(self._findings(pack, bds, causes, responses)))

    @staticmethod
    def _findings(pack, bds, causes, responses) -> dict:
        total = pack["metrics"]["returns"]
        drill = {(r.get("group_by"), r.get("filter", {}).get("cause")): r for r in responses if "rows" in r}
        out = []
        for i, c in enumerate(causes[:3], 1):
            cause = c["group"]
            ev = [{"ref": "breakdown:root_cause", "finding": f"{c['count']} of {total} returns are {cause}"}]
            affected = {"sizes": [], "colors": [], "batches": [], "warehouses": [], "attributes": []}
            label = cause.replace("_", " ")
            for dim in SPLIT.get(cause, []):
                b, ref = bds.get(f"breakdown:{dim}"), f"breakdown:{dim}"
                if (dim, cause) in drill:
                    b, ref = drill[(dim, cause)], drill[(dim, cause)]["ref_id"]
                elif not b or b["filter"].get("cause") != cause:
                    continue
                top = [r for r in _rows(b) if r["share"] >= 0.25][:2]
                if top:
                    ev.append({"ref": ref, "finding": f"{top[0]['count']} of the {cause} returns are {dim} {top[0]['group']}"})
                    key = {"size": "sizes", "model": "attributes", "batch": "batches", "warehouse": "warehouses",
                           "color": "colors"}[dim]
                    affected[key] = [r["group"] for r in top]
                    label = f"{dim} {', '.join(affected[key])}"
                    break
            media = bds.get("breakdown:media")
            if media and media["filter"].get("cause") == cause and _rows(media):
                m = _rows(media)[0]
                ev.append({"ref": "breakdown:media", "finding": f"{m['count']} photo findings show {m['group'].replace('_', ' ')}"})
            for f in [f for f in pack["feedback"] if f["cause"] == cause and f["comment"]][:2]:
                ev.append({"ref": f["return_id"], "finding": f["comment"][:120]})
            if cause in ("size_fit", "not_as_described"):
                for lc in pack["listing_changes"][:1]:
                    ev.append({"ref": lc["id"], "finding": f"Listing field {lc['field']} changed during the period"})
                    affected["attributes"].append(lc["field"])
            out.append({"cause_id": f"c{i}", "title": TITLE[cause].format(v=label), "cause": cause,
                        "owner": OWNER[cause], "supporting_returns": c["count"], "share": c["share"],
                        "evidence": ev, "counter_evidence": [], "affected": affected})
        rejected = [{"hypothesis": f"{r['group'].replace('_', ' ')} problem",
                     "reason": f"Only {r['count']} returns, below the evidence bar", "refs": ["breakdown:root_cause"]}
                    for r in _rows(bds.get("breakdown:root_cause")) if r not in causes and r["count"] >= 2]
        summary = (f"Main driver of returns: {out[0]['title']}." if out
                   else "No single cause meets the evidence bar; returns are spread across causes.")
        return {"summary": summary, "root_causes": out, "rejected_hypotheses": rejected,
                "data_notes": pack["completeness_notes"]}


FIX = {"size_fit": ("Re-measure the garments for {v} and correct the size chart so it matches them.", "size_chart ({v})"),
       "defect_quality": ("Hold remaining stock from {v} and get the supplier to fix the defect before restocking.", "{v}"),
       "damaged_in_transit": ("Add protective packaging for this product and review handling at {v}.", "packaging at {v}"),
       "wrong_item": ("Audit picking and SKU labels for this product at {v}.", "picking at {v}"),
       "not_as_described": ("Replace the listing photos and description so they match the product shipped.", "listing photos")}


class StubSolutionLlm(_StubBase):
    model: str = "stub-solution-llm"

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        ctx = _context(llm_request.contents)
        fixes = []
        for rc in ctx["findings"]["root_causes"]:
            if rc["owner"] == "none" or rc["cause"] not in FIX:
                continue
            a = rc["affected"]
            v = ", ".join([*(f"size {s}" for s in a["sizes"]), *(f"batch {b}" for b in a["batches"]),
                           *(f"the {w} warehouse" for w in a["warehouses"])]) or "the affected stock"
            fix, target = FIX[rc["cause"]]
            fixes.append({"cause_id": rc["cause_id"], "fix": fix.format(v=v), "target": target.format(v=v),
                          "owner": rc["owner"]})
        yield _text(json.dumps({"fixes": fixes}))


KEYWORDS = {"size": "size", "fit": "size", "colour": "color", "color": "color", "shade": "color",
            "warehouse": "warehouse", "transit": "warehouse", "batch": "batch", "week": "week", "month": "week",
            "photo": "media_finding", "picture": "media_finding", "model": "model",
            "cause": "root_cause", "why": "root_cause", "reason": "root_cause", "return": "root_cause"}
CAUSE_WORDS = {"defect": "defect_quality", "damage": "damaged_in_transit", "wrong": "wrong_item",
               "described": "not_as_described", "mind": "changed_mind"}


class StubQaLlm(_StubBase):
    model: str = "stub-qa-llm"

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        contents = llm_request.contents
        ctx = _context(contents)
        q = ctx["question"].lower()
        m = re.search(r"\bsize\s+([a-z0-9]{1,3})\b", q)  # "size L" is a filter, not the split
        words = [w.rstrip("s") if w.rstrip("s") in KEYWORDS else w
                 for w in re.findall(r"[a-z]+", q[:m.start()] + q[m.end():] if m else q)]
        dims = [KEYWORDS[w] for w in words if w in KEYWORDS]
        if not dims and not m:
            yield _text(json.dumps({"answer": "I can only answer questions about this product's returns.",
                                    "evidence": [], "related_return_ids": [], "enough_data": False}))
            return
        dim = next((d for d in dims if d != "root_cause"), "root_cause")
        cause = next((c for w, c in CAUSE_WORDS.items() if w in q), None)
        flt = {"cause": cause} if cause else {}
        if m:
            flt["size"] = m.group(1).upper()
        pack = ctx["evidence_pack"]
        b = next((b for b in pack["breakdowns"] if b["group_by"] == dim and b["filter"] == flt), None)
        responses = _tool_responses(contents)
        if b is None and not responses:
            args = dict(product_id=ctx["product_id"], group_by=dim, **flt)
            yield _call("get_return_breakdown", args)
            return
        if b is None:
            b = responses[-1] | {"id": responses[-1].get("ref_id")}
        rows = _rows(b)
        if not rows:
            yield _text(json.dumps({"answer": "There is not enough data to answer that for this product.",
                                    "evidence": [], "related_return_ids": [], "enough_data": False}))
            return
        split = ", ".join(f"{r['group']} {r['count']}" for r in rows[:4])
        scope = " and ".join(f"{k} {v}" for k, v in flt.items())
        finding = f"Returns{' with ' + scope if scope else ''} by {dim}: {split}"
        related = [f["return_id"] for f in pack["feedback"] if not cause or f["cause"] == cause][:3]
        yield _text(json.dumps({"answer": f"{finding}. The largest group is {rows[0]['group']} with {rows[0]['count']} returns.",
                                "evidence": [{"ref": b["id"], "finding": finding}],
                                "related_return_ids": related, "enough_data": True}))
