"""Scripted stand-in for Gemini, plugged into ADK as a BaseLlm.

It behaves like a model: reads the context from the prompt, asks ADK to call
analyze_media then search_policy, then writes a ReturnVerdict JSON from what the tools returned.
Swap to real Gemini with LLM_MODE=gemini; nothing else changes.
"""
import json
from collections import Counter
from typing import AsyncGenerator

from google.adk.models import BaseLlm
from google.adk.models.base_llm import LlmCapabilities
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

CONTEXT_MARKER = "CONTEXT_JSON:"
RETRY_MARKER = "Your previous output was rejected"

DEFECT_TO_CAUSE = {
    "sole_separation": "defect_quality", "stitching_failure": "defect_quality",
    "transit_damage": "damaged_in_transit", "color_mismatch": "not_as_described",
    "wrong_item": "wrong_item", "length_shorter_than_chart": "size_fit", "fit_issue": "size_fit",
}
POLICY_QUERY = {
    "size_fit": "size and fit", "defect_quality": "defective items", "damaged_in_transit": "damaged in transit",
    "wrong_item": "wrong item delivered", "not_as_described": "not as described",
    "changed_mind": "change of mind", "suspicious": "suspicious returns", "other": "return window",
}


def _texts(contents, role):
    return [p.text for c in contents if c.role == role for p in (c.parts or []) if p.text]


def _responses(contents) -> dict:
    out = {}
    for c in contents:
        for p in c.parts or []:
            if p.function_response:
                out[p.function_response.name] = p.function_response.response
    return out


def _call(name, args) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(name=name, args=args))]))


def _text(s) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=s)]))


class StubLlm(BaseLlm):
    model: str = "stub-return-llm"
    behavior: str = "normal"  # tests: "bad_json_once" (retry path), "bad_json_always" (failure path)

    @classmethod
    def supported_models(cls) -> list[str]:
        return []

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=False)

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        contents = llm_request.contents
        first_user = _texts(contents, "user")[0]
        ctx = json.loads(first_user.split(CONTEXT_MARKER, 1)[1])
        responses = _responses(contents)
        media_ids = [m["id"] for m in ctx["media"]]

        if media_ids and "analyze_media" not in responses:
            profile = ctx.get("category_profile") or {}
            yield _call("analyze_media", dict(media_refs=media_ids,
                                              listing_image_urls=ctx["listing"]["listing_image_urls"],
                                              focus=profile.get("media_focus", "")))
            return

        findings = (responses.get("analyze_media") or {}).get("findings", [])
        cause = self._cause(ctx, findings)
        if "search_policy" not in responses:
            yield _call("search_policy", dict(query_text=POLICY_QUERY[cause]))
            return

        retried = any(RETRY_MARKER in t for t in _texts(contents, "user"))
        if self.behavior == "bad_json_always" or (self.behavior == "bad_json_once" and not retried):
            yield _text("Here is my verdict: not json")
            return
        yield _text(json.dumps(self._verdict(ctx, findings, responses.get("search_policy") or {}, cause)))

    # ── the "reasoning" ──
    @staticmethod
    def _cause(ctx, findings) -> str:
        stated = ctx["return"]["stated_reason"]
        votes = Counter(DEFECT_TO_CAUSE[f["defect_type"]] for f in findings if f.get("defect_type") in DEFECT_TO_CAUSE)
        return votes.most_common(1)[0][0] if votes else stated

    @staticmethod
    def _verdict(ctx, findings, policy, cause) -> dict:
        stated = ctx["return"]["stated_reason"]
        order, ship = ctx["order"], ctx["shipment"]
        conf = 0.86 - 0.04 * len(ctx["context_notes"])
        if not findings:
            conf = 0.50  # nothing to judge from the media
        if cause == "damaged_in_transit":
            conf += 0.05 if (ship and ship["damage_flag"]) else -0.15
        conf = round(min(max(conf, 0.0), 0.97), 2)

        evidence = [{"ref": f["media_id"], "finding": f["description"]} for f in findings[:2]]
        evidence.append({"ref": order["id"], "finding": f"Ordered {json.dumps(order['variant'])}, batch {order['batch_id']}"})
        if ship and cause == "damaged_in_transit":
            evidence.append({"ref": ship["id"], "finding": f"Shipped from {ship['warehouse']}, damage_flag={ship['damage_flag']}"})
        if policy.get("sections"):
            top = policy["sections"][0]
            evidence.append({"ref": top["id"], "finding": f"{top['title']}: policy applies"})

        worst = max(findings, key=lambda f: ["none", "low", "medium", "high"].index(f["severity"]), default=None)
        mismatch = stated != cause
        action = "manual_review" if conf < 0.6 else "request_more_evidence" if conf < 0.7 else "approve_return"
        return {
            "root_cause": cause, "stated_reason": stated, "reason_mismatch": mismatch, "confidence": conf,
            "explanation": (f"Customer selected '{stated}' but the evidence indicates {cause}." if mismatch
                            else f"Stated reason '{stated}' is consistent with the media and order context."),
            "evidence": evidence,
            "media_findings": ({k: worst[k] for k in ("defect_type", "severity", "visible_damage", "matches_listing")}
                               if worst else None),
            "recommended_action": action, "needs_manual_review": conf < 0.6,
        }
