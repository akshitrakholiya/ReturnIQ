# ReturnIQ — Relational Modeling & Read-Only Toolset Skill

## Core Objective
Ensure that data persistence strictly models the 18 relational tables and that the 13 shared tools remain read-only, parameterized, and secure[cite: 4, 8, 17, 18].

## Data Modeling & Persistence Rules
1. **18-Table Schema Integrity:**
   - Strictly adhere to the AlloyDB DDL schema: `seller`, `category_profile`, `product`, `listing_change`, `customer`, `order`, `shipment`, `return`, `return_media`, `media_finding`, `return_analysis`, `return_review`, `evidence_pack`, `report_run`, `product_report`, `product_qa`, `policy`, `cost_model`[cite: 17, 18].
   - Product-level metrics (order counts, return counts, baseline comparisons) must be computed via SQL views or functions, never persisted statically in product rows[cite: 7, 18].

2. **Read-Only Tools Implementation:**
   - Implement the 13 shared Python tools across 5 toolsets[cite: 4, 10, 11]:
     - **Order & Shipment:** `get_return()`, `get_order_details()`, `get_shipment()`, `get_customer_return_history()`[cite: 10].
     - **Product Catalog:** `get_product_listing()`, `get_listing_changes()`, `get_category_profile()`[cite: 10].
     - **Product Intelligence:** `get_product_history()`, `get_category_baseline()`, `get_return_breakdown()`, `get_return_feedback()`[cite: 11].
     - **Multimodal:** `analyze_media()`[cite: 11].
     - **Policy:** `search_policy()`[cite: 11].
   - All tools must use parameterized SQL with read-only DB permissions[cite: 8, 11]. No `INSERT`, `UPDATE`, or `DELETE` statements allowed in tool code[cite: 5].

3. **Breakdown Engine Flexibility:**
   - `get_return_breakdown()` must accept dynamic `group_by` targets (`root_cause`, `size`, `color`, `week`, `warehouse`, `batch`, `reason_mismatch`, `media_finding`) and arbitrary filter dicts[cite: 11].
   - Return aggregations must use `final_root_cause` if reviewed, or fall back to the AI-predicted `root_cause`[cite: 2, 11].