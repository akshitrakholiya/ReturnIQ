# ReturnIQ — Google ADK Agent Orchestration & Prompt Guardrails Skill

## Core Objective
Orchestrate reasoning agents (Return Agent, RCA Agent, Solution Agent, Q&A Agent) using Google ADK with strict tool caps, function binding, and persona boundaries[cite: 4, 5, 8, 9].

## Agent Implementation Directives
1. **Sequential Chain (RCA -> Solution):**
   - Bind the RCA Agent and Solution Agent into a `SequentialAgent` pipeline (`ProductAnalysis`)[cite: 9].
   - The RCA Agent writes findings (`RCAFindings`) into the session state; the Solution Agent consumes `{findings}` + `listing` + `profile` and generates fixes[cite: 2, 9].
   - The Solution Agent calls NO drill-down tools; its job is exclusively to produce actionable, attribute-level fixes[cite: 9, 10, 14].

2. **Tool Call Caps & Timeouts:**
   - Flow A Return Agent: maximum 3 tool calls, 60s timeout[cite: 8, 11].
   - Flow B RCA Agent: maximum 6 tool calls[cite: 2, 8, 11].
   - Flow B Q&A Agent: maximum 5 tool calls[cite: 2, 8, 11].

3. **Evidence Pack Precedence (Q&A Agent):**
   - The Q&A Agent must inspect the provided `EvidencePack` and `ProductReport` FIRST[cite: 8, 19].
   - It is permitted to invoke drill-down tools (`get_return_breakdown`, `get_return_feedback`) only if the pack does not contain the answer[cite: 8, 11, 19].
   - If data is still insufficient, set `enough_data: false` rather than guessing[cite: 1, 2, 19].

4. **Data Privacy Guardrails:**
   - Customer names and sensitive details must NEVER be exposed in agent context or prompt traces[cite: 8]. Pass opaque IDs (`customer_id`, `order_id`, `return_id`) only[cite: 8].