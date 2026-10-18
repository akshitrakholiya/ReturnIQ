"""Flow A Return Agent: ADK LlmAgent that analyzes media, searches policy, returns ReturnVerdict JSON."""
import json
import re
import time
import uuid
from dataclasses import dataclass, field

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.stub_model import CONTEXT_MARKER, RETRY_MARKER, StubLlm
from google.adk.models import Gemini

from app.core.config import gemini_client_kwargs, gemini_retry_options, key_label, settings
from app.tools.multimodal import analyze_media
from app.tools.policy import search_policy

INSTRUCTION = f"""You are the ReturnIQ Return Agent. You review ONE customer return and recommend what to do.
A human reviewer makes the final decision.

You receive the return context as JSON after '{CONTEXT_MARKER}'. Follow these rules:
1. In your FIRST step call analyze_media AND search_policy together (both calls in the same step).
   For analyze_media pass all media ids, the listing image URLs and the category profile's
   media_focus; skip it only if there is no media. For search_policy use the topic that matches
   the stated reason and comment. Use the category profile to decide what to check.
2. Compare the customer's stated reason and comment with what the media and the context show.
3. Only if the media shows a different cause than the stated one, call search_policy a second time
   for that cause.
4. Never conclude anything about something listed in context_notes; that data is missing.
5. Cite evidence only with IDs that appear in the context or tool results (media ids like m_1,
   order id, shipment id, policy ids like policy_2.1). Never invent IDs.
6. Write numbers only as they appear in the context or tool results. Do no arithmetic.
7. Customer names and contact details are never provided. Do not guess them.
8. Use at most {settings.max_return_tool_calls} tool calls.

Reply with ONLY a JSON object, no markdown, in exactly this shape:
{{"root_cause": one of size_fit|defect_quality|damaged_in_transit|wrong_item|not_as_described|changed_mind|suspicious|other,
 "stated_reason": "<the customer's stated reason>",
 "reason_mismatch": true|false,
 "confidence": 0.0-1.0,
 "explanation": "<one or two sentences>",
 "evidence": [{{"ref": "<id>", "finding": "<what that item shows>"}}],
 "media_findings": {{"defect_type": str|null, "severity": "none|low|medium|high", "visible_damage": bool, "matches_listing": bool|null}} or null,
 "recommended_action": approve_return|request_more_evidence|reject_return|manual_review,
 "needs_manual_review": true|false}}"""


@dataclass
class TurnResult:
    text: str
    tool_calls: list[dict] = field(default_factory=list)      # trace: name, args, ms
    tool_results: list[dict] = field(default_factory=list)    # name, response (for the checks)
    tokens_in: int | None = None
    tokens_out: int | None = None


def _model(name: str | None = None, key: str | None = None):
    if settings.llm_mode == "stub":
        return StubLlm()
    return Gemini(model=name or settings.return_model, retry_options=gemini_retry_options(),
                  client_kwargs=gemini_client_kwargs(key))


class ReturnAgentSession:
    """One analysis: a fresh agent + session. send() can be called again to retry with feedback."""

    def __init__(self, model: str | None = None, key: str | None = None):
        self.calls_used = 0
        llm = _model(model, key)
        self.key_label = key_label(key)
        self.model_name = getattr(llm, "model", None) or str(llm)

        def limit_tool_calls(tool, args, tool_context):
            self.calls_used += 1
            if self.calls_used > settings.max_return_tool_calls:
                return {"error": "tool call limit reached; answer with what you have"}
            return None

        self.agent = LlmAgent(name="return_agent", model=llm, instruction=INSTRUCTION,
                              tools=[analyze_media, search_policy], before_tool_callback=limit_tool_calls)
        self.sessions = InMemorySessionService()
        self.runner = Runner(app_name="returniq", agent=self.agent, session_service=self.sessions)
        self.session_id = uuid.uuid4().hex

    async def send(self, message: str) -> TurnResult:
        if not getattr(self, "_created", False):
            await self.sessions.create_session(app_name="returniq", user_id="api", session_id=self.session_id)
            self._created = True
        result, started = TurnResult(text=""), {}
        async for ev in self.runner.run_async(user_id="api", session_id=self.session_id,
                                              new_message=types.Content(role="user", parts=[types.Part(text=message)])):
            for fc in ev.get_function_calls():
                started[fc.id or fc.name] = time.perf_counter()
                result.tool_calls.append({"name": fc.name, "args": dict(fc.args or {}), "ms": None})
            for fr in ev.get_function_responses():
                t0 = started.get(fr.id or fr.name)
                for tc in result.tool_calls:
                    if tc["name"] == fr.name and tc["ms"] is None:
                        tc["ms"] = round((time.perf_counter() - t0) * 1000) if t0 else None
                        break
                result.tool_results.append({"name": fr.name, "response": fr.response})
            if ev.usage_metadata:
                result.tokens_in = (result.tokens_in or 0) + (ev.usage_metadata.prompt_token_count or 0)
                result.tokens_out = (result.tokens_out or 0) + (ev.usage_metadata.candidates_token_count or 0)
            if ev.is_final_response() and ev.content and ev.content.parts:
                result.text = "".join(p.text or "" for p in ev.content.parts)
        return result


def first_message(context: dict) -> str:
    return f"Analyze this return.\n{CONTEXT_MARKER}\n{json.dumps(context, default=str)}"


def retry_message(problem: str) -> str:
    return f"{RETRY_MARKER}: {problem}\nReturn corrected JSON only, in the exact shape from your instructions."


def parse_json(text: str) -> dict:
    """Model output -> dict. Tolerates ```json fences and surrounding prose."""
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object found in the reply")
    return json.loads(t[start:end + 1])
