# ReturnIQ — Multimodal Image Verification & Storage Harness Skill

## Core Objective
Manage multi-modal asset paths, image degradation testing, and multimodal Gemini Vision integration via the `analyze_media()` tool[cite: 4, 8, 10, 11].

## Media Rules & Integration Directives
1. **Hierarchical Storage Convention:**
   - Standardize media asset paths strictly under local or cloud buckets:
     - Listing shots: `./mock_storage/listings/<product_id>/<product_id>_<angle>.jpg`
     - Return uploads: `./mock_storage/returns/<product_id>/<return_id>/<return_id>_defect.jpg`
   - Store only storage URLs/paths in the database (`return_media.storage_url`, `product.listing_image_urls`), never raw image bytes[cite: 5, 17, 18].

2. **Multimodal Analysis (`analyze_media`):**
   - Read image paths from disk or Google Cloud Storage[cite: 4, 5].
   - Provide Gemini with the customer return photo alongside reference catalog shots and the category profile's `media_focus` (e.g., "fit, length, color shade, stitching, stains")[cite: 1, 10, 11].
   - Map output to the `media_finding` record: `defect_type`, `severity`, `visible_damage`, `matches_listing`, and `description`[cite: 10, 18].

3. **Fallback & Manual Review Triggers:**
   - If media is missing, corrupted, or unreadable, analyze using text notes only, record an evidence entry `"media unavailable"`, and force `needs_manual_review = true`[cite: 20].
   - If the Return Agent's output confidence is `< 0.6`, force `needs_manual_review = true`[cite: 6, 14, 20].