# ReturnIQ — Multimodal Image Verification & Storage Harness Skill

## Core Objective
Manage multi-modal asset paths, image degradation testing, and multimodal Gemini Vision integration via the `analyze_media()` tool[cite: 4, 8, 10, 11].

## Media Rules & Integration Directives
1. **Hierarchical Storage Convention:**
   - Media paths are relative to the media storage root (`MEDIA_DIR`, default `server/media_uploads/`; later a GCS bucket):
     - Listing shots: `listings/<product_id>/<product_id>_<angle>.jpg`
     - Return uploads from the dataset: `returns/<product_id>/<return_id>/<return_id>_defect.jpg`
     - Customer uploads: `uploads/<uuid>.<ext>`
   - Store only that path in the database (`return_media.storage_url`, `product.listing_image_urls`): no `local://` prefix,
     no host, never a signed URL, never raw image bytes. `app/services/storage.py` resolves the location and builds the
     view URL at read time; only external listing images set by `scripts/set_listing_images.py` may be full `https://` URLs.
     Older databases with `local://...` values: `python -m scripts.migrate_media_paths`[cite: 5, 17, 18].

2. **Multimodal Analysis (`analyze_media`):**
   - Read image paths from disk or Google Cloud Storage[cite: 4, 5].
   - Provide Gemini with the customer return photo alongside reference catalog shots and the category profile's `media_focus` (e.g., "fit, length, color shade, stitching, stains")[cite: 1, 10, 11].
   - Map output to the `media_finding` record: `defect_type`, `severity`, `visible_damage`, `matches_listing`, and `description`[cite: 10, 18].

3. **Fallback & Manual Review Triggers:**
   - If media is missing, corrupted, or unreadable, analyze using text notes only, record an evidence entry `"media unavailable"`, and force `needs_manual_review = true`[cite: 20].
   - If the Return Agent's output confidence is `< 0.6`, force `needs_manual_review = true`[cite: 6, 14, 20].