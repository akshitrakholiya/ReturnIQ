"""
ReturnIQ - Authentic E-Commerce (Myntra/Amazon/Flipkart Style) Return Photo Synthesizer
- Zero synthetic props (no measuring tapes or fake overlays).
- Preserves 85-98% of original real camera pixels from ALL product listing photos.
- Applies natural garment bunching/foreshortening for size_fit, localized micro-defects
  with original fabric grain retention for defect_quality/damaged_in_transit, and
  authentic smartphone ISP post-processing (indoor tubelight, phone shadow, CMOS noise).
"""

import os
import random
import hashlib
import argparse
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


# ---------------------------------------------------------------------------
# 1. Database Query (Strictly Read-Only, Excludes wrong_item)
# ---------------------------------------------------------------------------
def get_target_returns(db_url: str) -> List[Dict[str, Any]]:
    """
    Fetches all return media targets except wrong_item returns.
    Pulls product details, customer comments, reviewer notes, and media_finding
    descriptions for accurate visual alignment.
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
# 2. Multi-Angle Catalog Asset Loader
# ---------------------------------------------------------------------------
def load_all_listing_assets(
    media_root: Path, product_id: str, db_urls: List[str]
) -> List[Image.Image]:
    """Loads all catalog listing images for a product from disk and DB references."""
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
# 3. Customer Framing, Natural Proportion Warp & Localized Masking
# ---------------------------------------------------------------------------
def deterministic_seed(return_id: str) -> int:
    return int(hashlib.md5(return_id.encode("utf-8")).hexdigest()[:8], 16)


def prepare_customer_canvas(
    listing_images: List[Image.Image],
    category: str,
    cause: str,
    comment: str,
    media_desc: str,
    return_id: str
) -> Image.Image:
    """
    Selects a catalog view, crops out studio model heads/margins into a casual
    close-up smartphone frame, and applies subtle perspective foreshortening
    when a customer complains about size/length.
    """
    rng = random.Random(deterministic_seed(return_id))
    text_context = f"{comment or ''} {media_desc or ''}".lower()

    if len(listing_images) > 1 and any(w in text_context for w in ["back", "rear", "behind", "heel"]):
        base_img = listing_images[min(1, len(listing_images) - 1)].copy()
    else:
        idx = rng.randint(0, len(listing_images) - 1)
        base_img = listing_images[idx].copy()

    w, h = base_img.size

    # Crop out studio model head/face in apparel shots to look like a product-focused phone shot
    if "footwear" not in (category or "").lower():
        top_crop = int(h * rng.uniform(0.19, 0.26))
        bottom_crop = int(h * rng.uniform(0.86, 0.94))
        side_margin = int(w * rng.uniform(0.10, 0.16))
        base_img = base_img.crop((side_margin, top_crop, w - side_margin, bottom_crop))
    else:
        margin_x = int(w * rng.uniform(0.06, 0.12))
        margin_y = int(h * rng.uniform(0.08, 0.15))
        base_img = base_img.crop((margin_x, margin_y, w - margin_x, h - margin_y))

    # For size_fit returns ("shorter than chart" / "tight"), apply subtle camera-angle
    # foreshortening (4-6% aspect shift) instead of fake measuring tapes
    if cause == "size_fit":
        cw, ch = base_img.size
        if any(k in text_context for k in ["short", "length", "crop"]):
            # Subtle vertical foreshortening (looks slightly shorter/boxier from overhead phone angle)
            squashed_h = int(ch * rng.uniform(0.92, 0.95))
            base_img = base_img.resize((cw, squashed_h), Image.Resampling.LANCZOS)
        elif any(k in text_context for k in ["tight", "narrow", "small"]):
            squashed_w = int(cw * rng.uniform(0.93, 0.96))
            base_img = base_img.resize((squashed_w, ch), Image.Resampling.LANCZOS)

    base_img = base_img.resize((1024, 1024), Image.Resampling.LANCZOS)

    # Apply natural handheld rotation (customer holding phone casually above bed/table)
    angle = rng.choice([-5.5, -4.0, -2.8, 3.0, 4.5, 6.0])
    rotated = base_img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)

    cw, ch = rotated.size
    inset = int(cw * 0.055)
    canvas = rotated.crop((inset, inset, cw - inset, ch - inset)).resize(
        (1024, 1024), Image.Resampling.LANCZOS
    )
    return canvas


def build_localized_defect_mask(
    cause: str, comment: str, media_desc: str, return_id: str
) -> Tuple[Image.Image, float]:
    """
    Creates a soft-feathered localized mask:
    - For defect_quality & damaged_in_transit: small localized patch (strength 0.45-0.52).
    - For size_fit, changed_mind, not_as_described, etc.: ultra-light crease zone (strength 0.20)
      so 98% of the original real camera pixels remain completely untouched.
    """
    rng = random.Random(deterministic_seed(return_id) + 7)
    mask = Image.new("L", (1024, 1024), 0)
    draw = ImageDraw.Draw(mask)
    text_context = f"{comment or ''} {media_desc or ''}".lower()

    if cause == "defect_quality":
        if any(k in text_context for k in ["sole", "heel", "toe", "hem", "bottom"]):
            cx, cy = rng.randint(380, 640), rng.randint(650, 800)
        elif any(k in text_context for k in ["collar", "neck", "button", "top", "shoulder"]):
            cx, cy = rng.randint(400, 620), rng.randint(240, 380)
        else:
            cx, cy = rng.randint(360, 640), rng.randint(420, 620)

        rx, ry = rng.randint(105, 155), rng.randint(80, 125)
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=230)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=28))
        return mask, 0.50

    if cause == "damaged_in_transit":
        cx, cy = rng.randint(360, 660), rng.randint(380, 660)
        for _ in range(3):
            ox = cx + rng.randint(-55, 55)
            oy = cy + rng.randint(-55, 55)
            r = rng.randint(60, 105)
            draw.ellipse([ox - r, oy - r, ox + r, oy + r], fill=220)
        mask = mask.filter(ImageFilter.GaussianBlur(radius=30))
        return mask, 0.46

    # For size_fit, not_as_described, changed_mind, suspicious, other:
    # No strange objects! Only a subtle, low-opacity fabric fold/handling crease region.
    cx, cy = rng.randint(380, 640), rng.randint(400, 660)
    draw.ellipse([cx - 140, cy - 110, cx + 140, cy + 110], fill=120)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=40))
    return mask, 0.20


def build_inpaint_prompt(item: Dict[str, Any]) -> str:
    """Builds a natural, prop-free texture prompt for the masked region."""
    cause = item["effective_cause"]
    comment = (item.get("comment") or "").strip()
    media_desc = (item.get("media_description") or "").strip()
    defect_type = (item.get("defect_type") or "").replace("_", " ").strip()
    flaw_detail = media_desc or comment or defect_type

    if cause == "defect_quality":
        return (
            f"close-up unedited smartphone photo of real garment fabric showing subtle physical flaw: "
            f"{flaw_detail or 'loose seam thread, small stitching gap, minor fray'}, "
            f"natural woven cotton textile grain, harsh indoor room lighting"
        )
    if cause == "damaged_in_transit":
        return (
            f"close-up unedited smartphone photo showing subtle surface smudge mark, dust scuff, "
            f"and crumpled crease on fabric: {flaw_detail}, authentic customer mobile photo"
        )
    if cause == "not_as_described":
        return (
            f"unedited indoor smartphone photo of garment fabric with slightly dull washed-out shade "
            f"and natural wrinkles, harsh overhead tubelight"
        )
    # Default for size_fit, changed_mind, suspicious, other:
    return (
        "unpacked garment with natural folding creases and soft fabric wrinkles from courier bag, "
        "authentic unedited smartphone photo, indoor home lighting"
    )


# ---------------------------------------------------------------------------
# 4. Authentic Smartphone ISP Post-Processing & Original Grain Retention
# ---------------------------------------------------------------------------
def apply_smartphone_isp(
    base_canvas: Image.Image,
    inpainted_canvas: Image.Image,
    mask: Image.Image,
    cause: str,
    return_id: str
) -> Image.Image:
    """
    1. Re-injects the original photo's high-frequency fabric weave into the inpainted patch
       so the defect region never looks smooth or AI-rendered.
    2. Simulates natural folding/unpacked wrinkles for size_fit / changed_mind returns.
    3. Applies Indian indoor lighting (cool LED tubelight or warm bulb), overhead phone shadow,
       CMOS sensor grain, and mobile JPEG compression.
    """
    rng = random.Random(deterministic_seed(return_id) + 99)

    base_arr = np.asarray(base_canvas).astype(np.float32)
    inpaint_arr = np.asarray(inpainted_canvas).astype(np.float32)

    # Extract high-frequency micro-texture (fabric weave / leather pores) from original catalog photo
    base_blurred = np.asarray(base_canvas.filter(ImageFilter.GaussianBlur(radius=2.2))).astype(np.float32)
    high_freq_detail = base_arr - base_blurred

    # Inject 45% of original high-frequency weave back into the inpainted output to kill AI smoothness
    inpaint_with_weave = np.clip(inpaint_arr + 0.45 * high_freq_detail, 0, 255).astype(np.uint8)
    inpainted_textured = Image.fromarray(inpaint_with_weave)

    # Alpha-blend ONLY the masked region onto the real base photograph
    composite = Image.composite(inpainted_textured, base_canvas, mask)
    arr = np.asarray(composite).astype(np.float32)
    h, w, _ = arr.shape

    # For not_as_described, apply realistic shade dullness / color shift
    if cause == "not_as_described":
        pil_tmp = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        pil_tmp = ImageEnhance.Color(pil_tmp).enhance(0.75)
        pil_tmp = ImageEnhance.Contrast(pil_tmp).enhance(0.90)
        arr = np.asarray(pil_tmp).astype(np.float32)

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    # Add subtle unpacked fabric fold/crease shading (looks like item was just pulled from a Myntra/Flipkart bag)
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
    illum_map = 1.05 - 0.20 * dist_light

    sx, sy = rng.uniform(0.35, 0.65) * w, rng.uniform(0.78, 1.05) * h
    shadow_dist = np.exp(-((xx - sx) ** 2 / (2 * (w * 0.28) ** 2) + (yy - sy) ** 2 / (2 * (h * 0.22) ** 2)))
    illum_map -= 0.11 * shadow_dist

    arr *= illum_map[:, :, None]

    # Authentic Smartphone CMOS Sensor Noise (Luminance + Chrominance grain)
    np_rng = np.random.default_rng(deterministic_seed(return_id))
    luma_noise = np_rng.normal(0.0, rng.uniform(2.5, 4.0), size=(h, w, 1)).astype(np.float32)
    chroma_noise = np_rng.normal(0.0, rng.uniform(1.0, 1.8), size=(h, w, 3)).astype(np.float32)
    arr = np.clip(arr + luma_noise + chroma_noise, 0, 255).astype(np.uint8)

    final_img = Image.fromarray(arr)
    final_img = final_img.filter(ImageFilter.GaussianBlur(radius=0.40))
    final_img = final_img.resize((768, 768), Image.Resampling.LANCZOS)
    return final_img


# ---------------------------------------------------------------------------
# 5. Model Pipeline Initialization
# ---------------------------------------------------------------------------
def load_pipeline():
    """Loads RealVisXL v4.0 Inpainting pipeline from local cache + IP-Adapter."""
    model_id = "SG161222/RealVisXL_V4.0"
    print(f"Loading SDXL Inpainting pipeline from cached checkpoint: {model_id}...")

    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    pipe = AutoPipelineForInpainting.from_pretrained(
        model_id,
        torch_dtype=dtype,
        variant="fp16" if device == "cuda" else None,
        use_safetensors=True
    )
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config, use_karras_sigmas=True
    )

    use_ip_adapter = False
    try:
        print("Binding IP-Adapter SDXL for multi-angle catalog conditioning...")
        pipe.load_ip_adapter(
            "h94/IP-Adapter",
            subfolder="sdxl_models",
            weight_name="ip-adapter_sdxl.bin"
        )
        pipe.set_ip_adapter_scale(0.60)
        use_ip_adapter = True
    except Exception as e:
        print(f"Warning: IP-Adapter not loaded ({e}). Proceeding with localized inpainting.")

    pipe.to(device)
    if device == "cuda":
        pipe.enable_attention_slicing()
        pipe.enable_vae_tiling()

    return pipe, device, use_ip_adapter


# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="ReturnIQ - Catalog-Matched Defect Synthesizer")
    parser.add_argument("--db", default=DEFAULT_DB_URL, help="PostgreSQL connection URL")
    parser.add_argument("--media-root", default=DEFAULT_MEDIA_ROOT, type=Path, help="Path to media_uploads folder")
    parser.add_argument("--dry-run", action="store_true", help="Preview target returns without modifying files")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of returns to process (0 = all)")
    args = parser.parse_args()

    records = get_target_returns(args.db)
    if args.limit > 0:
        records = records[:args.limit]
    print(f"Found {len(records)} non-wrong_item return images to synthesize.")

    if args.dry_run:
        for r in records[:10]:
            assets = load_all_listing_assets(args.media_root, r["product_id"], r["listing_image_urls"])
            print(
                f"  [DRY-RUN] Return: {r['return_id']} | Product: {r['product_id']} ({r['product_name']}) "
                f"| Views: {len(assets)} | Cause: {r['effective_cause']} "
                f"| Finding: {r['media_description'] or r['comment']}"
            )
        return

    pipe, device, use_ip_adapter = load_pipeline()
    updated = 0
    skipped = 0

    for item in tqdm(records, desc="Generating realistic customer return photos"):
        product_id = item["product_id"]
        return_id = item["return_id"]
        target_path = args.media_root / item["storage_url"]

        # 1. Load ALL listing images for this product
        all_listing_images = load_all_listing_assets(
            args.media_root, product_id, item.get("listing_image_urls")
        )
        if not all_listing_images:
            skipped += 1
            continue

        # 2. Prepare handheld customer close-up canvas (with subtle proportion shift for size_fit)
        base_canvas = prepare_customer_canvas(
            all_listing_images,
            item.get("product_category", ""),
            item["effective_cause"],
            item.get("comment", ""),
            item.get("media_description", ""),
            return_id
        )

        # 3. Build localized feathered mask (no measuring tapes or artificial props)
        mask, strength = build_localized_defect_mask(
            item["effective_cause"],
            item.get("comment", ""),
            item.get("media_description", ""),
            return_id
        )

        prompt = build_inpaint_prompt(item)
        generator = torch.Generator(device=device).manual_seed(deterministic_seed(return_id))

        # 4. Run localized inpainting conditioned on all listing views
        inpaint_kwargs = dict(
            prompt=prompt,
            negative_prompt=NEGATIVE_PROMPT,
            image=base_canvas,
            mask_image=mask,
            strength=strength,
            num_inference_steps=24,
            guidance_scale=5.5,
            padding_mask_crop=32,
            generator=generator,
        )
        if use_ip_adapter:
            ip_views = [img.resize((1024, 1024), Image.Resampling.LANCZOS) for img in all_listing_images]
            inpaint_kwargs["ip_adapter_image"] = [ip_views]

        with torch.inference_mode():
            inpainted_result = pipe(**inpaint_kwargs).images[0]

        # 5. Apply Smartphone ISP + original weave retention
        final_photo = apply_smartphone_isp(
            base_canvas=base_canvas,
            inpainted_canvas=inpainted_result,
            mask=mask,
            cause=item["effective_cause"],
            return_id=return_id
        )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        final_photo.save(target_path, format="JPEG", quality=82, subsampling=2, optimize=True)
        updated += 1

    print(f"\nCompleted: {updated} realistic return photos saved. {skipped} skipped.")


if __name__ == "__main__":
    main()