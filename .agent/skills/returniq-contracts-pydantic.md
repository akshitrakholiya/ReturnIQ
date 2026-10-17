# ReturnIQ — Pydantic Contract Adherence & Schema Validation Skill

## Core Objective
Enforce strict validation across every pipeline transition using Pydantic (v2) models matching `flow_b_schemas.py` and Flow A specifications[cite: 2, 14].

## Validation & Recovery Directives
1. **Strict Type Checking:**
   - Every step must consume and produce strictly typed objects[cite: 2]:
     - Step 1: `ReportRequest` -> `CacheCheckResult`[cite: 2]
     - Step 2: `HealthCheckInput` -> `HealthCheckResult`[cite: 2]
     - Step 3: `EvidencePackInput` -> `EvidencePack`[cite: 2]
     - Step 4: `RCAInput` -> `RCAFindings`[cite: 2]
     - Step 5: `SolutionInput` -> `SolutionOutput`[cite: 2]
     - Step 6: `ScoringInput` -> `ProductReport`[cite: 2]
     - Seller Q&A: `QAInput` -> `QAAnswer` -> `QAResponse`[cite: 2]
   - Never accept arbitrary JSON dictionaries between internal pipeline modules[cite: 2].

2. **Enum Restraints:**
   - Root causes must strictly use the `RootCause` enum: `size_fit`, `defect_quality`, `damaged_in_transit`, `wrong_item`, `not_as_described`, `changed_mind`, `suspicious`, `other`[cite: 2].
   - Owners must strictly be `seller`, `logistics`, or `none`[cite: 2].

3. **Error Handling & Retry Loop:**
   - If an agent generates invalid JSON or fails Pydantic schema validation, trigger a single automated retry passing the validation error back to the model[cite: 9, 19].
   - If the retry fails, log the run as `analysis_failed`[cite: 19].