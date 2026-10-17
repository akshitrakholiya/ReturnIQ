"""Flow B agents: RCA, Solution and Q&A (ADK LlmAgents). Instructions follow the HLD/LLD stage 2/3 and Q&A rules.
The API runs them (app/agents/runner.py), validates their JSON and checks every citation and number."""
from app.agents.runner import AgentSpec
from app.agents.stub_flow_b import StubQaLlm, StubRcaLlm, StubSolutionLlm
from app.agents.stub_model import CONTEXT_MARKER
from app.core.config import settings
from app.tools.product_catalog import get_listing_changes
from app.tools.product_intelligence import get_product_history, get_return_breakdown, get_return_feedback

CAUSES = "size_fit|defect_quality|damaged_in_transit|wrong_item|not_as_described|changed_mind|suspicious|other"
CITING = """- Cite evidence only with IDs from the evidence pack ('metrics', 'breakdown:size', 'listing', 'profile',
  listing change ids like 'lc_3', return ids like 'r_101') or the ref_id of a tool result ('tool:1'). Never invent IDs.
- Write numbers exactly as they appear in the evidence or tool results. Do no arithmetic: no sums, differences,
  ratios or percentages you computed yourself. A share like 0.604 may be written as 60%.
- Never conclude anything the completeness_notes say is missing."""

RCA_INSTRUCTION = f"""You are the ReturnIQ RCA Agent. You find the root causes of one product's returns.
You receive an evidence pack as JSON after '{CONTEXT_MARKER}'. Every item in it has an ID.

Method:
1. Read the pack and the category profile's listing_checks; use the profile to decide what to check.
2. Form 2-4 hypotheses from the biggest causes, stated-vs-actual mismatches and concentrations
   (a size, color, batch, warehouse or week holding most of a cause's returns; a listing change before a rise).
3. For each hypothesis find supporting AND contradicting evidence in the pack. Call a drill-down tool only where
   the pack cannot answer (the pack's splits are filtered to the top cause; e.g. use
   get_return_breakdown(group_by="batch", cause="defect_quality") for another cause). At most {settings.max_rca_tool_calls} tool calls.
4. Accept a root cause only with >= {settings.rca_min_returns} supporting returns and >= {round(settings.rca_min_share * 100)}% share of the
   period's returns; otherwise put it in rejected_hypotheses with the reason.
5. Owner: seller (product or listing), logistics (warehouse, transit, picking), none (customer preference).
6. Each root cause needs at least 2 evidence items, ideally from different sources (numbers, comments/notes,
   photo findings, listing). Put evidence against it in counter_evidence.
{CITING}

Reply with ONLY a JSON object, no markdown, in exactly this shape:
{{"summary": "<one or two sentences>",
 "root_causes": [{{"cause_id": "c1", "title": "<specific: what, where>", "cause": {CAUSES},
   "owner": "seller|logistics|none", "supporting_returns": <int from the evidence>, "share": <float from the evidence>,
   "evidence": [{{"ref": "<id>", "finding": "<short claim>"}}], "counter_evidence": [{{"ref": "<id>", "finding": "..."}}],
   "affected": {{"sizes": [], "colors": [], "batches": [], "warehouses": [], "attributes": ["size_chart.length_cm"]}}}}],
 "rejected_hypotheses": [{{"hypothesis": "...", "reason": "...", "refs": ["<id>"]}}],
 "data_notes": ["<what is missing or thin>"]}}
root_causes may be empty when nothing meets the bar."""

SOLUTION_INSTRUCTION = f"""You are the ReturnIQ Solution Agent. You turn root causes into specific fixes for the seller.
You receive the RCA findings, the product listing and the category profile as JSON after '{CONTEXT_MARKER}'.

Rules:
1. One fix per root cause, linked by cause_id, with the same owner. Owner "none" gets no fix.
2. Name the exact attribute, size, batch, warehouse or photo: "Change size L length from 72 cm to 69 cm",
   not "improve the size chart". Use the listing's attributes and the findings' affected values.
3. Do not invent causes or numbers: use only numbers that appear in the findings or the listing.

Reply with ONLY a JSON object, no markdown:
{{"fixes": [{{"cause_id": "c1", "fix": "<specific action>", "target": "<e.g. size_chart.L.length_cm, batch B36, listing photo 1>",
  "owner": "seller|logistics"}}]}}"""

QA_INSTRUCTION = f"""You are the ReturnIQ Q&A Agent. You answer a seller's question about ONE product's returns.
You receive the question, the saved product report, its evidence pack and the last turns of the conversation
as JSON after '{CONTEXT_MARKER}'.

Rules:
1. Check the report and the evidence pack first. Call tools only if they cannot answer
   (at most {settings.max_qa_tool_calls} calls), e.g. get_return_breakdown(group_by="warehouse", size="L", cause="size_fit").
2. Answer only about this product's returns. For anything else reply "I can only answer questions about this
   product's returns." with enough_data false.
3. If the data is too thin to answer, say so and set enough_data false. Keep answers short and plain.
4. related_return_ids: up to 5 return ids that illustrate the answer, taken from the pack or tool results.
{CITING}

Reply with ONLY a JSON object, no markdown:
{{"answer": "<plain answer>", "evidence": [{{"ref": "<id>", "finding": "<short claim>"}}],
 "related_return_ids": ["r_101"], "enough_data": true|false}}"""

DRILL_DOWN = [get_return_breakdown, get_return_feedback, get_listing_changes, get_product_history]

RCA = AgentSpec(name="rca", instruction=RCA_INSTRUCTION, tools=DRILL_DOWN, max_tool_calls=settings.max_rca_tool_calls,
                stub=StubRcaLlm, models=settings.rca_models)
SOLUTION = AgentSpec(name="solution", instruction=SOLUTION_INSTRUCTION, stub=StubSolutionLlm,
                     models=settings.return_models)
QA = AgentSpec(name="qa", instruction=QA_INSTRUCTION, tools=DRILL_DOWN, max_tool_calls=settings.max_qa_tool_calls,
               stub=StubQaLlm, models=settings.return_models)
