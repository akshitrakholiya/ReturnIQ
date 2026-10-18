"""
ReturnIQ - Diversified E-Commerce (Myntra/Amazon/Flipkart Style) Return Photo Synthesizer
Generates 5 distinct, photorealistic customer return archetypes from catalog listings:
  1. color_shade_mismatch  - Distinct dye-lot hue shift / washed-out faded cloth shade
  2. stain_on_cloth        - Capillary liquid/oil/mud/transit smudge soaked into fabric weave
  3. minor_split_tear      - Seam split, ripped stitching gap, frayed threads, or sole gap
  4. fabric_quality_defect - Cracked/peeling print, heavy pilling fuzz, rough abraded weave
  5. size_fit_unpacked     - Unpacked crumpled garment with proportion foreshortening
Strictly excludes wrong_item returns and preserves 100% product silhouette identity.
"""

import os
import gc
import random
import hashlib
import argparse
from collections import Counter
from pathlib import Path
from typing import List, Dict, Any, Tuple

import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor
import torch
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
from tqdm import tqdm
from diffusers import AutoPipelineForInpainting, DPMSolverMultistepScheduler

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/returniq"
)
DEFAULT_MEDIA_ROOT = Path("media_uploads")

NEGATIVE_PROMPT = (
    "measuring tape, ruler, numbers, text, watermark, logo, AI generated, CGI, "
    "3d render, illustration, painting, smooth plastic texture, airbrushed, "
    "studio model face, fashion photoshoot, professional lighting, oversaturated, "
    "cartoon, unreal engine, deformed"
)

ARCHETYPES = [
    "color_shade_mismatch",
    "stain_on_cloth",
    "minor_split_tear",
    "fabric_quality_defect",
    "size_fit_unpacked",
]


# ---------------------------------------------------------------------------
# 1. Database Query (Strictly Read-Only, Excludes wrong_item)
# ---------------------------------------------------------------------------
def get_target_returns(db_url: str) -> List[Dict[str, Any]]:
    """
    Fetches all return media targets for fashion catalog products (P%)
    except wrong_item returns.
    """
    conn = psycopg2.connect(db_url)
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    query = """
    SELECT 
        r.id AS return_id,
        r.product_id,
        r.stated_reason::text AS stated_reason,
        r.comment,
        p.name AS product_name,
        p.category AS product_category,
        p.listing_image_urls,
        o.variant,
        rv.note AS reviewer_note,
        mf.defect_type,
        mf.description AS media_description,
        mf.visible_damage,
        mf.matches_listing,
        COALESCE(
            el.true_root_cause::text,
            rv.final_root_cause::text,
            ra.root_cause::text,
            r.stated_reason::text
        ) AS effective_cause,
        rm.storage_url
    FROM public.returns r
    JOIN public.return_media rm ON rm.return_id = r.id
    JOIN public.product p ON p.id = r.product_id
    LEFT JOIN public.orders o ON o.id = r.order_id
    LEFT JOIN public.return_analysis ra ON ra.return_id = r.id AND ra.is_current = true
    LEFT JOIN public.media_finding mf ON mf.return_id = r.id AND mf.media_id = rm.id
    LEFT JOIN public.return_review rv ON rv.return_id = r.id
    LEFT JOIN public.eval_label el ON el.subject_id = r.id AND el.subject_type = 'return'
    WHERE r.stated_reason != 'wrong_item'
      AND COALESCE(el.true_root_cause::text, '') != 'wrong_item'
      AND COALESCE(rv.final_root_cause::text, '') != 'wrong_item'
      AND COALESCE(ra.root_cause::text, '') != 'wrong_item'
      AND COALESCE(mf.matches_listing, true) = true
      AND r.product_id LIKE 'P%'
    ORDER BY r.product_id, r.id;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# 2. Deterministic Archetype Classifier & Diversifier
# ---------------------------------------------------------------------------
def deterministic_seed(return_id: str) -> int:
    return int(hashlib.md5(return_id.encode("utf-8")).hexdigest()[:8], 16)


def classify_defect_archetype(item: Dict[str, Any], index_in_product: int) -> str:
    """
    Determines the exact visual defect archetype for a return.
    1. Honors explicit keywords in media_finding, reviewer_note, or comment first.
    2. Maps root causes to concrete visual flaws.
    3. Diversifies generic/unannotated returns so every product folder has a realistic
       mix of stains, seam splits, color shade mismatches, quality wear, and fit shots.
    """
    cause = item.get("effective_cause") or item.get("stated_reason") or "other"
    defect_type = (item.get("defect_type") or "").lower()
    media_desc = (item.get("media_description") or "").lower()
    comment = (item.get("comment") or "").lower()
    note = (item.get("reviewer_note") or "").lower()
    combined = f"{defect_type} {media_desc} {note} {comment}"

    # 1. Explicit media_finding or comment keyword match
    if any(k in combined for k in ["stain", "spot", "smudge", "dirty", "oil", "grease", "spill", "mark", "mud", "water"]):
        return "stain_on_cloth"
    if any(k in combined for k in ["split", "tear", "torn", "rip", "seam", "stitch", "thread", "fray", "hole", "sole", "detach", "gap", "unravel", "broken"]):
        return "minor_split_tear"
    if any(k in combined for k in ["color", "colour", "shade", "faded", "dull", "bleach", "discolor", "darker", "lighter", "different shade", "mismatch"]):
        return "color_shade_mismatch"
    if any(k in combined for k in ["pill", "lint", "fuzz", "print", "peel", "crack", "rough", "cheap", "thin", "worn", "used", "material"]):
        return "fabric_quality_defect"

    # 2. If media_finding explicitly locked a size finding (e.g., "shorter_than_chart"), keep size_fit
    if any(k in f"{defect_type} {media_desc}" for k in ["shorter", "smaller", "larger", "tight", "loose_fit", "chart"]):
        # Even within size_fit, give 35% of them a slight washed/shade or handling scuff so photos look varied
        if index_in_product % 3 == 1:
            return "color_shade_mismatch"
        return "size_fit_unpacked"

    # 3. Root-cause driven mapping with diversification
    if cause == "not_as_described":
        return "color_shade_mismatch" if index_in_product % 2 == 0 else "fabric_quality_defect"
    if cause == "damaged_in_transit":
        return "stain_on_cloth" if index_in_product % 2 == 0 else "minor_split_tear"
    if cause == "defect_quality":
        cycle = ["minor_split_tear", "stain_on_cloth", "fabric_quality_defect"]
        return cycle[index_in_product % len(cycle)]
    if cause == "suspicious":
        return "stain_on_cloth" if index_in_product % 2 == 0 else "fabric_quality_defect"

    # 4. Diversify generic size_fit / changed_mind / other returns that lack locked media_finding
    # Real e-commerce return queues have mixed visual flaws even when customers click the first dropdown
    diversified_cycle = [
        "size_fit_unpacked",
        "color_shade_mismatch",
        "stain_on_cloth",
        "minor_split_tear",
        "fabric_quality_defect",
    ]
    return diversified_cycle[(deterministic_seed(item["return_id"]) + index_in_product) % len(diversified_cycle)]


# ---------------------------------------------------------------------------
# 3. Multi-Angle Catalog Asset Loader
# ---------------------------------------------------------------------------
def load_all_listing_assets(
    media_root: Path, product_id: str, db_urls: List[str]
) -> List[Image.Image]:
    candidate_paths: List[Path] = []

    for rel_url in (db_urls or []):
        clean_rel = rel_url.replace("local://", "").lstrip("/")
        p = media_root / clean_rel
        if p.exists() and p not in candidate_paths:
            candidate_paths.append(p)

    listing_dir = media_root / "listings" / product_id
    if listing_dir.exists():
        for p in sorted(listing_dir.glob("*.jpg")):
            if p not in candidate_paths:
                candidate_paths.append(p)

    images = []
    for p in candidate_paths:
        try:
            img = Image.open(p).convert("RGB")
            images.append(img)
        except Exception:
            continue

    return images


# ---------------------------------------------------------------------------
# 4. Customer Framing & Garment Foreground Segmentation
# ---------------------------------------------------------------------------
def prepare_customer_canvas(
    listing_images: List[Image.Image],
    category: str,
    archetype: str,
    comment: str,
    media_desc: str,
    return_id: str,
    target_dim: int = 768
) -> Image.Image:
    """
    Crops studio margins and model heads into an authentic close-up customer
    smartphone frame (Myntra/Flipkart/Amazon review & return photo style).
    """
    rng = random.Random(deterministic_seed(return_id))
    text_context = f"{comment or ''} {media_desc or ''}".lower()

    if len(listing_images) > 1 and any(w in text_context for w in ["back", "rear", "behind", "heel"]):
        base_img = listing_images[min(1, len(listing_images) - 1)].copy()
    else:
        idx = rng.randint(0, len(listing_images) - 1)
        base_img = listing_images[idx].copy()

    w, h = base_img.size

    if "footwear" not in (category or "").lower():
        # Tighter crop for split/stain macro shots; torso crop for shade/size shots
        if archetype in ("minor_split_tear", "stain_on_cloth"):
            top_crop = int(h * rng.uniform(0.24, 0.34))
            bottom_crop = int(h * rng.uniform(0.78, 0.88))
            side_margin = int(w * rng.uniform(0.16, 0.24))
        else:
            top_crop = int(h * rng.uniform(0.18, 0.25))
            bottom_crop = int(h * rng.uniform(0.86, 0.94))
            side_margin = int(w * rng.uniform(0.10, 0.16))
        base_img = base_img.crop((side_margin, top_crop, w - side_margin, bottom_crop))
    else:
        margin_x = int(w * rng.uniform(0.06, 0.14))
        margin_y = int(h * rng.uniform(0.08, 0.16))
        base_img = base_img.crop((margin_x, margin_y, w - margin_x, h - margin_y))

    if archetype == "size_fit_unpacked":
        cw, ch = base_img.size
        if any(k in text_context for k in ["short", "length", "crop"]):
            base_img = base_img.resize((cw, int(ch * rng.uniform(0.91, 0.94))), Image.Resampling.LANCZOS)
        else:
            base_img = base_img.resize((int(cw * rng.uniform(0.92, 0.95)), ch), Image.Resampling.LANCZOS)

    base_img = base_img.resize((target_dim, target_dim), Image.Resampling.LANCZOS)

    angle = rng.choice([-5.0, -3.5, -2.2, 2.5, 4.0, 5.5])
    rotated = base_img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)

    cw, ch = rotated.size
    inset = int(cw * 0.055)
    canvas = rotated.crop((inset, inset, cw - inset, ch - inset)).resize(
        (target_dim, target_dim), Image.Resampling.LANCZOS
    )
    return canvas


def extract_garment_foreground_mask(canvas: Image.Image) -> np.ndarray:
    """
    Estimates a soft alpha mask [0..1] of the garment/shoe foreground vs studio background
    by sampling border background color and combining with a central spatial prior.
    """
    arr = np.asarray(canvas).astype(np.float32)
    h, w, _ = arr.shape

    # Sample studio background color from outer corners
    corners = np.concatenate([
        arr[:20, :20].reshape(-1, 3),
        arr[:20, -20:].reshape(-1, 3),
        arr[-20:, :20].reshape(-1, 3),
        arr[-20:, -20:].reshape(-1, 3),
    ], axis=0)
    bg_color = np.median(corners, axis=0)

    # Color distance from background
    color_dist = np.linalg.norm(arr - bg_color[None, None, :], axis=2)
    fg_raw = np.clip((color_dist - 18.0) / 38.0, 0.0, 1.0)

    # Central spatial prior so center of garment is always included even if light-colored
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    center_prior = np.exp(-(((xx - w * 0.5) / (w * 0.36)) ** 2 + ((yy - h * 0.52) / (h * 0.38)) ** 2))
    combined = np.clip(np.maximum(fg_raw, center_prior * 0.85), 0.0, 1.0)

    mask_pil = Image.fromarray((combined * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=8))
    return np.asarray(mask_pil).astype(np.float32) / 255.0


# ---------------------------------------------------------------------------
# 5. Localized Defect Masking & Prompts for SDXL Inpainting
# ---------------------------------------------------------------------------
def find_seam_or_fabric_hotspot(canvas: Image.Image, rng: random.Random, prefer_edges: bool) -> Tuple[int, int]:
    """
    Finds an authentic seam/stitching edge (for minor_split_tear) or a solid fabric
    region (for stain_on_cloth) within the central garment area.
    """
    gray = np.asarray(canvas.convert("L")).astype(np.float32)
    h, w = gray.shape
    gx = np.abs(np.gradient(gray, axis=1))
    gy = np.abs(np.gradient(gray, axis=0))
    grad = gx + gy

    # Search inside central garment box [28%..72%]
    y0, y1 = int(h * 0.28), int(h * 0.72)
    x0, x1 = int(w * 0.28), int(w * 0.72)

    best_pt = (w // 2, h // 2)
    best_score = -1e9

    for _ in range(25):
        cx = rng.randint(x0, x1)
        cy = rng.randint(y0, y1)
        patch = grad[cy - 24:cy + 24, cx - 24:cx + 24]
        mean_edge = float(np.mean(patch))
        score = mean_edge if prefer_edges else -abs(mean_edge - 8.0)
        if score > best_score:
            best_score = score
            best_pt = (cx, cy)

    return best_pt


def build_archetype_mask_and_prompt(
    canvas: Image.Image,
    archetype: str,
    item: Dict[str, Any]
) -> Tuple[Image.Image, float, str, Tuple[int, int]]:
    """
    Builds the localized inpainting mask, denoising strength, prompt, and defect center (cx, cy).
    """
    return_id = item["return_id"]
    rng = random.Random(deterministic_seed(return_id) + 13)
    w, h = canvas.size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)

    comment = (item.get("comment") or "").strip()
    media_desc = (item.get("media_description") or "").strip()
    flaw_text = media_desc or comment

    if archetype == "minor_split_tear":
        cx, cy = find_seam_or_fabric_hotspot(canvas, rng, prefer_edges=True)
        # Elongated seam split / tear region
        angle_rad = rng.uniform(-0.8, 0.8)
        length = int(w * rng.uniform(0.14, 0.20))
        dx = int(np.cos(angle_rad) * length)
        dy = int(np.sin(angle_rad) * length)
        draw.line(
            [(cx - dx, cy - dy), (cx + dx, cy + dy)],
            fill=255,
            width=int(w * 0.085)
        )
        mask = mask.filter(ImageFilter.GaussianBlur(radius=12))
        prompt = (
            f"macro close-up smartphone photo of a torn seam split in cloth, ripped stitching gap "
            f"showing loose frayed cotton threads and small fabric tear, {flaw_text}, "
            f"raw unedited textile fibers, indoor lighting"
        )
        return mask, 0.72, prompt, (cx, cy)

    if archetype == "stain_on_cloth":
        cx, cy = find_seam_or_fabric_hotspot(canvas, rng, prefer_edges=False)
        for _ in range(4):
            ox = cx + rng.randint(-int(w * 0.06), int(w * 0.06))
            oy = cy + rng.randint(-int(h * 0.06), int(h * 0.06))
            rx = rng.randint(int(w * 0.05), int(w * 0.09))
            ry = rng.randint(int(h * 0.05), int(h * 0.09))
            draw.ellipse([ox - rx, oy - ry, ox + rx, oy + ry], fill=245)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=16))
        prompt = (
            f"close-up unedited smartphone photo of a dirty dark liquid grease stain and brownish "
            f"oil smudge soaked into woven cloth fabric, {flaw_text}, authentic stain blotch on garment"
        )
        return mask, 0.66, prompt, (cx, cy)

    if archetype == "fabric_quality_defect":
        cx, cy = find_seam_or_fabric_hotspot(canvas, rng, prefer_edges=True)
        rx, ry = int(w * 0.14), int(h * 0.12)
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=235)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=20))
        prompt = (
            f"close-up unedited smartphone photo of damaged rough garment fabric with heavy lint pilling fuzz, "
            f"snagged pulled threads, faded cracked print texture, {flaw_text}, worn cloth quality issue"
        )
        return mask, 0.62, prompt, (cx, cy)

    # For color_shade_mismatch & size_fit_unpacked:
    # Keep 98% original real camera pixels and apply subtle fabric crease inpainting
    cx, cy = w // 2, h // 2
    rx, ry = int(w * 0.12), int(h * 0.10)
    draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=100)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=28))
    prompt = (
        "unpacked garment with natural folding creases and soft fabric wrinkles from courier bag, "
        "authentic unedited smartphone photo, indoor home lighting"
    )
    return mask, 0.22, prompt, (cx, cy)


# ---------------------------------------------------------------------------
# 6. Physical Defect Overlays (Color Shade Shift, Capillary Stain, Seam Split)
# ---------------------------------------------------------------------------
def apply_color_shade_mismatch(arr: np.ndarray, fg_mask: np.ndarray, rng: random.Random) -> np.ndarray:
    """
    Shifts the garment's color shade/hue/saturation strictly within the garment foreground
    while preserving 100% of the real photographic weave, shadows, and stitching highlights.
    """
    pil_img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("HSV")
    hsv = np.asarray(pil_img).astype(np.float32)

    mode = rng.choice(["hue_shift_warm", "hue_shift_cool", "washed_out_fade", "uneven_dye_lot"])

    if mode == "hue_shift_warm":
        # Noticeable dye lot shift (+20 to +34 on 0..255 hue wheel) + slightly duller saturation
        hsv[:, :, 0] = (hsv[:, :, 0] + rng.uniform(20.0, 34.0)) % 255.0
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * rng.uniform(0.72, 0.85), 0, 255)
    elif mode == "hue_shift_cool":
        hsv[:, :, 0] = (hsv[:, :, 0] - rng.uniform(20.0, 34.0)) % 255.0
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * rng.uniform(0.70, 0.85), 0, 255)
    elif mode == "washed_out_fade":
        # Heavy washed-out chalky fade (common Myntra/Flipkart "color looks dull/faded" complaint)
        hsv[:, :, 0] = (hsv[:, :, 0] + rng.uniform(-12.0, 12.0)) % 255.0
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * rng.uniform(0.42, 0.58), 0, 255)
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 0.92 + 22.0, 0, 255)
    else:
        # Uneven bleached/discolored patch across part of the garment
        h, w, _ = hsv.shape
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        px, py = rng.uniform(0.35, 0.65) * w, rng.uniform(0.35, 0.65) * h
        patch = np.exp(-(((xx - px) / (w * 0.25)) ** 2 + ((yy - py) / (h * 0.25)) ** 2))
        hsv[:, :, 0] = (hsv[:, :, 0] + 26.0 * patch) % 255.0
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (1.0 - 0.52 * patch), 0, 255)
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] + 18.0 * patch, 0, 255)

    shifted_rgb = np.asarray(Image.fromarray(hsv.astype(np.uint8), mode="HSV").convert("RGB")).astype(np.float32)
    alpha = fg_mask[:, :, None]
    return arr * (1.0 - alpha) + shifted_rgb * alpha


def apply_capillary_fabric_stain(
    arr: np.ndarray, center: Tuple[int, int], rng: random.Random
) -> np.ndarray:
    """
    Multiplies a realistic liquid/oil/mud capillary stain (with darker dried outer tide-ring)
    directly into the underlying cloth weave so real fabric threads remain visible through the stain.
    """
    h, w, _ = arr.shape
    cx, cy = center
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    # Build organic multi-lobe blotch shape
    blotch = np.zeros((h, w), dtype=np.float32)
    for _ in range(5):
        ox = cx + rng.uniform(-w * 0.045, w * 0.045)
        oy = cy + rng.uniform(-h * 0.045, h * 0.045)
        rx = rng.uniform(w * 0.028, w * 0.065)
        ry = rng.uniform(h * 0.028, h * 0.065)
        theta = rng.uniform(0, np.pi)
        dx, dy = xx - ox, yy - oy
        rx_p = dx * np.cos(theta) + dy * np.sin(theta)
        ry_p = -dx * np.sin(theta) + dy * np.cos(theta)
        dist2 = (rx_p / rx) ** 2 + (ry_p / ry) ** 2
        blotch += np.exp(-dist2 * 1.4)

    blotch = np.clip(blotch / (np.max(blotch) + 1e-6), 0.0, 1.0)

    # Capillary coffee/oil ring effect (stronger concentration along outer drying boundary)
    core = np.clip((blotch - 0.25) / 0.75, 0.0, 1.0)
    perimeter_ring = np.exp(-((blotch - 0.38) / 0.11) ** 2) * (blotch > 0.18)
    stain_density = np.clip(0.65 * core + 0.45 * perimeter_ring, 0.0, 0.88)

    # Choose realistic stain tint (tea/coffee brown, dark machine oil/grease, or yellowish smudge)
    stain_tints = [
        np.array([0.46, 0.36, 0.26], dtype=np.float32),  # Coffee / mud brown stain
        np.array([0.38, 0.37, 0.35], dtype=np.float32),  # Dark transit grease / oil smudge
        np.array([0.58, 0.48, 0.30], dtype=np.float32),  # Yellowish-brown rust / warehouse moisture stain
    ]
    tint = rng.choice(stain_tints)[None, None, :]

    # Multiplicative absorption into real fabric weave
    s_map = stain_density[:, :, None]
    stained_arr = arr * (1.0 - s_map + s_map * tint)
    return np.clip(stained_arr, 0, 255)


def apply_physical_seam_split_detail(
    arr: np.ndarray, center: Tuple[int, int], rng: random.Random
) -> np.ndarray:
    """
    Reinforces the inpainted tear/split zone with a realistic narrow dark seam separation
    and fine frayed cross-threads so the split looks crisp like a macro phone photo.
    """
    h, w, _ = arr.shape
    cx, cy = center
    pil_img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Draw jagged narrow seam split / tear opening
    angle = rng.uniform(-0.75, 0.75)
    half_len = int(w * rng.uniform(0.055, 0.085))
    pts = []
    steps = 9
    for i in range(steps + 1):
        t = (i / steps) * 2.0 - 1.0
        px = cx + int(t * half_len * np.cos(angle) + rng.uniform(-2.5, 2.5))
        py = cy + int(t * half_len * np.sin(angle) + rng.uniform(-2.5, 2.5))
        pts.append((px, py))

    # Outer frayed lip shadow + inner split gap
    draw.line(pts, fill=(45, 38, 35, 135), width=6)
    draw.line(pts, fill=(18, 15, 14, 215), width=3)

    # Add 5-7 fine frayed loose threads bridging or hanging from the split
    local_rgb = arr[max(0, cy - 20):min(h, cy + 20), max(0, cx - 20):min(w, cx + 20)]
    thread_color = np.clip(np.mean(local_rgb, axis=(0, 1)) + 35.0, 90, 235).astype(int)
    t_col = (int(thread_color[0]), int(thread_color[1]), int(thread_color[2]), 185)

    for _ in range(6):
        p_idx = rng.randint(1, len(pts) - 2)
        bx, by = pts[p_idx]
        tx = bx + rng.randint(-18, 18)
        ty = by + rng.randint(-18, 22)
        mx = (bx + tx) // 2 + rng.randint(-5, 5)
        my = (by + ty) // 2 + rng.randint(-5, 5)
        draw.line([(bx, by), (mx, my), (tx, ty)], fill=t_col, width=1)

    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=0.6))
    composited = Image.alpha_composite(pil_img.convert("RGBA"), overlay).convert("RGB")
    return np.asarray(composited).astype(np.float32)


def apply_fabric_pilling_distress(
    arr: np.ndarray, center: Tuple[int, int], rng: random.Random
) -> np.ndarray:
    """
    Adds localized micro-pilling / lint balls and surface abrasion for fabric_quality_defect.
    """
    h, w, _ = arr.shape
    cx, cy = center
    np_rng = np.random.default_rng(rng.randint(1, 10_000_000))

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    zone = np.exp(-(((xx - cx) / (w * 0.13)) ** 2 + ((yy - cy) / (h * 0.13)) ** 2))

    # High-frequency lint/pilling speckles + local fade
    specks = (np_rng.random((h, w)) > 0.985).astype(np.float32)
    specks_img = Image.fromarray((specks * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=0.9))
    pilling_map = (np.asarray(specks_img).astype(np.float32) / 255.0) * zone

    # Slightly wash out the abraded zone and dot with tiny pilling knots
    arr = arr * (1.0 - 0.16 * zone[:, :, None]) + 28.0 * zone[:, :, None]
    arr = arr + pilling_map[:, :, None] * 55.0
    return np.clip(arr, 0, 255)


# ---------------------------------------------------------------------------
# 7. Authentic Smartphone ISP Post-Processing (Myntra/Flipkart/Amazon UGC Look)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 7. Authentic Smartphone ISP Post-Processing (Myntra/Flipkart/Amazon UGC Look)
# ---------------------------------------------------------------------------
def apply_smartphone_isp(
    base_canvas: Image.Image,
    inpainted_canvas: Image.Image,
    mask: Image.Image,
    archetype: str,
    defect_center: Tuple[int, int],
    return_id: str
) -> Image.Image:
    """
    Combines localized inpainting with physical defect layers and authentic smartphone
    ISP effects (indoor lighting, phone shadow, unpacking folds, CMOS grain).
    """
    # FIX: SDXL natively outputs 1024x1024. Force alignment with our memory-optimized canvas.
    if inpainted_canvas.size != base_canvas.size:
        inpainted_canvas = inpainted_canvas.resize(base_canvas.size, Image.Resampling.LANCZOS)

    rng = random.Random(deterministic_seed(return_id) + 99)

    base_arr = np.asarray(base_canvas).astype(np.float32)
    inpaint_arr = np.asarray(inpainted_canvas).astype(np.float32)

    # Retain 30% of original high-frequency weave inside inpainted region to prevent plastic sheen
    base_blurred = np.asarray(base_canvas.filter(ImageFilter.GaussianBlur(radius=2.0))).astype(np.float32)
    high_freq_detail = base_arr - base_blurred
    inpaint_with_weave = np.clip(inpaint_arr + 0.30 * high_freq_detail, 0, 255).astype(np.uint8)
    inpainted_textured = Image.fromarray(inpaint_with_weave)

    # Composite masked inpaint region onto real base photograph
    composite = Image.composite(inpainted_textured, base_canvas, mask)
    arr = np.asarray(composite).astype(np.float32)
    h, w, _ = arr.shape

    # Apply archetype-specific physical realism layer
    if archetype == "color_shade_mismatch":
        fg_mask = extract_garment_foreground_mask(base_canvas)
        arr = apply_color_shade_mismatch(arr, fg_mask, rng)
    elif archetype == "stain_on_cloth":
        arr = apply_capillary_fabric_stain(arr, defect_center, rng)
    elif archetype == "minor_split_tear":
        arr = apply_physical_seam_split_detail(arr, defect_center, rng)
    elif archetype == "fabric_quality_defect":
        arr = apply_fabric_pilling_distress(arr, defect_center, rng)

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    # Add subtle unpacked fabric fold/crease shading
    fold_angle = rng.uniform(0.3, 1.2)
    fold_freq = rng.uniform(2.5, 4.0)
    fold_wave = np.sin((xx * np.cos(fold_angle) + yy * np.sin(fold_angle)) / w * np.pi * fold_freq)
    arr *= (1.0 - 0.035 * fold_wave[:, :, None])

    # Indoor White Balance Shift (6500K cool tubelight vs 3200K warm bulb)
    lighting_mode = rng.choice(["cool_tubelight", "warm_bulb", "neutral_indoor"])
    if lighting_mode == "cool_tubelight":
        arr[:, :, 0] *= 0.96
        arr[:, :, 1] *= 1.01
        arr[:, :, 2] *= 1.05
    elif lighting_mode == "warm_bulb":
        arr[:, :, 0] *= 1.05
        arr[:, :, 1] *= 1.00
        arr[:, :, 2] *= 0.93

    # Directional Room Illumination + Subtle Phone/Hand Shadow
    lx, ly = rng.uniform(0.2, 0.8) * w, rng.uniform(0.0, 0.3) * h
    dist_light = np.sqrt((xx - lx) ** 2 + (yy - ly) ** 2) / (np.sqrt(w**2 + h**2))
    illum_map = 1.05 - 0.18 * dist_light

    sx, sy = rng.uniform(0.35, 0.65) * w, rng.uniform(0.78, 1.05) * h
    shadow_dist = np.exp(-((xx - sx) ** 2 / (2 * (w * 0.28) ** 2) + (yy - sy) ** 2 / (2 * (h * 0.22) ** 2)))
    illum_map -= 0.10 * shadow_dist

    arr *= illum_map[:, :, None]

    # Authentic Smartphone CMOS Sensor Noise (Luminance + Chrominance grain)
    np_rng = np.random.default_rng(deterministic_seed(return_id))
    luma_noise = np_rng.normal(0.0, rng.uniform(2.2, 3.6), size=(h, w, 1)).astype(np.float32)
    chroma_noise = np_rng.normal(0.0, rng.uniform(0.9, 1.6), size=(h, w, 3)).astype(np.float32)
    arr = np.clip(arr + luma_noise + chroma_noise, 0, 255).astype(np.uint8)

    final_img = Image.fromarray(arr)
    final_img = final_img.filter(ImageFilter.GaussianBlur(radius=0.35))
    final_img = final_img.resize((768, 768), Image.Resampling.LANCZOS)
    return final_img


# ---------------------------------------------------------------------------
# 8. Low-Memory Model Pipeline Initialization
# ---------------------------------------------------------------------------
def load_pipeline():
    """Loads RealVisXL v4.0 Inpainting pipeline with Mac MPS / CUDA memory slicing."""
    model_id = "SG161222/RealVisXL_V4.0"
    print(f"Loading SDXL Inpainting pipeline from cached checkpoint: {model_id}...")

    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    pipe = AutoPipelineForInpainting.from_pretrained(
        model_id,
        dtype=dtype,
        variant="fp16" if device == "cuda" else None,
        use_safetensors=True
    )
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config, use_karras_sigmas=True
    )

    # Enable memory optimizations compatible with diffusers SDXL
    pipe.enable_attention_slicing(1)
    if hasattr(pipe, "enable_vae_tiling"):
        pipe.enable_vae_tiling()
    if hasattr(pipe.vae, "enable_slicing"):
        pipe.vae.enable_slicing()

    pipe.to(device)
    print(f"Pipeline ready on {device} ({dtype}).")
    return pipe, device


# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="ReturnIQ - Diversified Realistic Return Photo Synthesizer")
    parser.add_argument("--db", default=DEFAULT_DB_URL, help="PostgreSQL connection URL")
    parser.add_argument("--media-root", default=DEFAULT_MEDIA_ROOT, type=Path, help="Path to media_uploads folder")
    parser.add_argument("--dry-run", action="store_true", help="Preview archetype distribution without modifying files")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of returns to process (0 = all)")
    args = parser.parse_args()

    records = get_target_returns(args.db)
    if args.limit > 0:
        records = records[:args.limit]
    print(f"Found {len(records)} non-wrong_item fashion return images to synthesize.")

    # Pre-compute per-product index and assign diversified archetypes
    product_counters: Dict[str, int] = Counter()
    archetype_counts: Dict[str, int] = Counter()

    for r in records:
        pid = r["product_id"]
        idx_in_prod = product_counters[pid]
        product_counters[pid] += 1
        arch = classify_defect_archetype(r, idx_in_prod)
        r["archetype"] = arch
        archetype_counts[arch] += 1

    print("\nPlanned Visual Defect Archetype Distribution:")
    for arch, count in archetype_counts.most_common():
        pct = (count / len(records) * 100) if records else 0
        print(f"  - {arch:<24}: {count:>3} photos ({pct:.1f}%)")

    if args.dry_run:
        print("\nSample Target Mappings (First 12):")
        for r in records[:12]:
            assets = load_all_listing_assets(args.media_root, r["product_id"], r["listing_image_urls"])
            print(
                f"  [DRY-RUN] {r['return_id']} ({r['product_id']}) -> Archetype: {r['archetype']:<22} "
                f"| DB Cause: {r['effective_cause']:<18} | Views: {len(assets)}"
            )
        return

    pipe, device = load_pipeline()
    updated = 0
    skipped = 0

    for item in tqdm(records, desc="Synthesizing diversified return photos"):
        product_id = item["product_id"]
        return_id = item["return_id"]
        archetype = item["archetype"]
        target_path = args.media_root / item["storage_url"]

        all_listing_images = load_all_listing_assets(
            args.media_root, product_id, item.get("listing_image_urls")
        )
        if not all_listing_images:
            skipped += 1
            continue

        # 1. Prepare 512x512 customer close-up canvas for fast, OOM-safe inpainting
        base_canvas = prepare_customer_canvas(
            all_listing_images,
            item.get("product_category", ""),
            archetype,
            item.get("comment", ""),
            item.get("media_description", ""),
            return_id,
            target_dim=512
        )

        # 2. Build archetype-specific mask, strength, prompt, and defect coordinates
        mask, strength, prompt, defect_center = build_archetype_mask_and_prompt(
            base_canvas, archetype, item
        )

        generator = torch.Generator(device="cpu").manual_seed(deterministic_seed(return_id))

        # 3. Run localized SDXL inpainting
        with torch.inference_mode():
            inpainted_result = pipe(
                prompt=prompt,
                negative_prompt=NEGATIVE_PROMPT,
                image=base_canvas,
                mask_image=mask,
                strength=strength,
                num_inference_steps=20,
                guidance_scale=5.5,
                generator=generator,
            ).images[0]

        # 4. Composite physical defect layer + Smartphone ISP post-processing
        final_photo = apply_smartphone_isp(
            base_canvas=base_canvas,
            inpainted_canvas=inpainted_result,
            mask=mask,
            archetype=archetype,
            defect_center=defect_center,
            return_id=return_id
        )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        final_photo.save(target_path, format="JPEG", quality=82, subsampling=2, optimize=True)
        updated += 1

        if updated % 8 == 0:
            gc.collect()
            if device == "mps":
                torch.mps.empty_cache()

    print(f"\nCompleted: {updated} diversified return photos saved. {skipped} skipped.")


if __name__ == "__main__":
    main()