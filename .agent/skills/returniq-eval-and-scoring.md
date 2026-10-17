# ReturnIQ — Deterministic Checks, Scoring & Cost Engine Skill

## Core Objective
Enforce the core architectural principle: **Code gathers and computes; agents reason**[cite: 3]. Gemini never performs math; all metrics and confidence scores are calculated in code[cite: 3].

## Deterministic Verification Rules
1. **Citation Check:**
   - Every item inside `evidence` must possess a `ref` string[cite: 2, 14].
   - The API verifies that every `ref` matches a known ID from the `EvidencePack` (`breakdown:*`, `listing`, `listing_change:*`, `profile`, or feedback `r_*`) or a tool call `ref_id` from that run[cite: 2, 20].
   - Drop any claim citing an unverified ID[cite: 3, 20].
   - If an issue is left with fewer than 2 valid evidence items, drop the entire root cause[cite: 20].

2. **Number Check:**
   - Scan agent summary text for numbers (percentages, return counts, dates, dimensions)[cite: 20].
   - Cross-check them against the `EvidencePack`[cite: 20]. Flag mismatches, trigger a single agent retry with the list of incorrect numbers, and strip uncorrected sentences if still failing[cite: 20].

3. **Deterministic Confidence Engine (0–100 Scale):**
   - Calculate confidence strictly via the code formula[cite: 20]:
     - **Share:** Issue's share of returns in the period (max 30 pts)[cite: 20, 21].
     - **Volume:** Number of supporting returns, capped at 20 (max 20 pts)[cite: 21].
     - **Agreement:** Count of agreeing sources (metrics, feedback comments, photo findings, listing checks) (max 30 pts)[cite: 21].
     - **Photo:** Share of photo findings that corroborate the defect (max 20 pts)[cite: 21].
     - **Contradiction:** Subtract points proportional to counter-evidence (up to -25 pts)[cite: 21].
   - Map scores to levels: High (>= 75), Medium (50–74), Low (< 50)[cite: 21].

4. **Impact Engine (INR):**
   - Calculate financial impact deterministically from `cost_model`[cite: 18, 21]:
     - `extra_returns_per_month = cause_returns - expected_returns_from_category_rate`[cite: 21]
     - `cost_per_return_inr = reverse_shipping + restocking + (write_off_rate * margin)`[cite: 18, 21]
     - `monthly_cost_inr = extra_returns_per_month * cost_per_return_inr`[cite: 21]