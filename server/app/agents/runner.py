"""Shared ADK plumbing for the Flow B agents (RCA, Solution, Q&A).

One fresh agent + session per attempt. Tools are wrapped so every call is traced, pinned to the
product being analyzed, capped, and tagged with a citable ref_id ('tool:1', 'tool:2', ...).
run_agent() handles model failover, timeouts and one retry with feedback for invalid output or
numbers that do not appear in the evidence (same policy as Flow A's analysis.py).
"""
import asyncio
import functools
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm, Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.agents.return_agent import parse_json, retry_message
from app.agents.stub_model import CONTEXT_MARKER
from app.core.config import gemini_chain, gemini_client_kwargs, gemini_retry_options, key_label, settings
from app.schemas.flow_b import ToolResult
from app.services.analysis import _quota_wait_seconds

log = logging.getLogger(__name__)


@dataclass
class AgentSpec:
    name: str                                   # 'rca', 'solution', 'qa' (agent_run.agent)
    instruction: str
    tools: list[Callable] = field(default_factory=list)
    max_tool_calls: int = 0
    stub: Callable[[], BaseLlm] | None = None   # used when LLM_MODE=stub
    models: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    output: BaseModel | None
    error: str | None
    model: str
    tool_results: list[ToolResult]              # of the session that produced the output
    trace: list[dict]                           # every tool call of every attempt: name, args, ms
    tokens: tuple[int | None, int | None]
    retried: bool
    duration_ms: int


class AgentSession:
    def __init__(self, spec: AgentSpec, model: str, product_id: str, key: str | None = None):
        self.spec, self.product_id = spec, product_id
        self.tool_results: list[ToolResult] = []
        self.calls = 0
        llm = spec.stub() if settings.llm_mode == "stub" and spec.stub else Gemini(
            model=model, retry_options=gemini_retry_options(), client_kwargs=gemini_client_kwargs(key))
        self.model_name = getattr(llm, "model", None) or str(llm)
        self.key_label = key_label(key)
        self.agent = LlmAgent(name=f"{spec.name}_agent", model=llm, instruction=spec.instruction,
                              tools=[self._traced(t) for t in spec.tools])
        self.sessions = InMemorySessionService()
        self.runner = Runner(app_name="returniq", agent=self.agent, session_service=self.sessions)
        self.session_id, self._created = f"{spec.name}-{time.time_ns()}", False

    def _traced(self, fn: Callable) -> Callable:
        @functools.wraps(fn)
        def tool(**kwargs) -> dict:
            self.calls += 1
            if self.calls > self.spec.max_tool_calls:
                return {"error": "tool call limit reached; answer with what you have"}
            if "product_id" in kwargs:
                kwargs["product_id"] = self.product_id  # agents only ever see this product's data
            ref = f"tool:{len(self.tool_results) + 1}"
            try:
                data = fn(**kwargs)
            except (ValueError, TypeError) as e:  # bad arguments: tell the model, let it carry on
                return {"error": str(e)[:300]}
            self.tool_results.append(ToolResult(ref_id=ref, tool=fn.__name__, args=kwargs, data=data))
            return {"ref_id": ref, **data}
        return tool

    async def send(self, message: str) -> tuple[str, list[dict], tuple[int, int]]:
        if not self._created:
            await self.sessions.create_session(app_name="returniq", user_id="api", session_id=self.session_id)
            self._created = True
        final, trace, started, tin, tout = "", [], {}, 0, 0
        async for ev in self.runner.run_async(user_id="api", session_id=self.session_id,
                                              new_message=types.Content(role="user", parts=[types.Part(text=message)])):
            for fc in ev.get_function_calls():
                started[fc.id or fc.name] = time.perf_counter()
                trace.append({"agent": self.spec.name, "name": fc.name, "args": dict(fc.args or {}), "ms": None})
            for fr in ev.get_function_responses():
                t0 = started.get(fr.id or fr.name)
                for tc in trace:
                    if tc["name"] == fr.name and tc["ms"] is None:
                        tc["ms"] = round((time.perf_counter() - t0) * 1000) if t0 else None
                        break
            if ev.usage_metadata:
                tin += ev.usage_metadata.prompt_token_count or 0
                tout += ev.usage_metadata.candidates_token_count or 0
            if ev.is_final_response() and ev.content and ev.content.parts:
                final = "".join(p.text or "" for p in ev.content.parts)
        return final, trace, (tin, tout)


async def run_agent(spec: AgentSpec, product_id: str, message: str, schema: type[BaseModel],
                    wrong_numbers: Callable[[BaseModel, list[ToolResult]], list[str]] | None = None) -> AgentResult:
    """Run one agent to a validated output. Infra errors fail over to the next API key, then the next model; invalid JSON or
    wrong numbers get one retry with feedback in the same session."""
    models = gemini_chain(spec.models or settings.return_models)  # (model, key) attempts
    mi, retries = 0, 0
    session, msg = AgentSession(spec, models[mi][0], product_id, models[mi][1]), message
    trace: list[dict] = []
    tokens = [None, None]
    output, error = None, None
    started = time.perf_counter()
    for attempt in range(len(models) + 1):
        last = attempt == len(models)
        try:
            text, t, tk = await asyncio.wait_for(session.send(msg), settings.llm_timeout_seconds)
        except Exception as e:  # timeout, quota (429), 5xx: the model is the problem, not the output
            error = (f"model timeout (> {settings.llm_timeout_seconds} s)" if isinstance(e, asyncio.TimeoutError)
                     else f"{type(e).__name__}: {str(e)[:300]}")
            log.warning("%s agent: %s (%s) failed: %s", spec.name, session.model_name, session.key_label, error[:160])
            if last:
                break
            if mi + 1 < len(models):
                mi += 1
            elif (wait := _quota_wait_seconds(e)):
                await asyncio.sleep(wait)
            session, msg = AgentSession(spec, models[mi][0], product_id, models[mi][1]), message
            continue
        trace += t
        tokens = [(tokens[0] or 0) + tk[0], (tokens[1] or 0) + tk[1]]
        try:
            output = schema.model_validate(parse_json(text))
        except (ValueError, ValidationError) as e:
            output, error = None, f"invalid output: {str(e)[:500]}"
            if retries or last:
                break
            retries += 1
            msg = retry_message(str(e)[:500])
            continue
        bad = wrong_numbers(output, session.tool_results) if wrong_numbers else []
        if bad and not retries and not last:
            retries += 1
            error = f"numbers not found in evidence: {bad}"
            msg = retry_message(f"these numbers do not appear in the evidence or tool results: {bad}. "
                                "Remove them or use the exact numbers from the evidence.")
            continue
        error = None  # accepted; any numbers still wrong are removed by the checks
        break
    return AgentResult(output=output if error is None else None, error=error, model=session.model_name,
                       tool_results=session.tool_results, trace=trace, tokens=tuple(tokens),
                       retried=retries > 0, duration_ms=int((time.perf_counter() - started) * 1000))


def context_message(task: str, context: Any) -> str:
    return f"{task}\n{CONTEXT_MARKER}\n{json.dumps(context, default=str)}"
