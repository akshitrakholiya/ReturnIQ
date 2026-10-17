"""Multimodal toolset (Flow A): analyze_media().

The backend is chosen by settings.llm_mode:
  stub   -> StubMediaAnalyzer: no vision. It fakes a finding from the customer's comment so the
            whole pipeline can be exercised. Every description is prefixed "[stub]".
  gemini -> GeminiMediaAnalyzer: sends the customer's photos/videos to Gemini and gets one
            structured finding per file.
"""
import re
from typing import Literal, Protocol

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import gemini_retry_options, settings
from app.services.storage import MAX_LISTING_IMAGES, load_bytes, storage
from app.tools._db import query

MAX_MEDIA = 5
SEVERITIES = ("none", "low", "medium", "high")


class MediaAnalyzer(Protocol):
    async def analyze(self, media_refs: list[str], listing_image_urls: list[str], focus: str) -> list[dict]: ...


# ───────────── stub ─────────────
# keyword -> (defect_type, severity, visible_damage, matches_listing); first match wins
_STUB_RULES = [
    (r"sole|separat|came off|detach", ("sole_separation", "high", True, True)),
    (r"stitch|seam|zip|peel|broke|stopped working|not working", ("stitching_failure", "medium", True, True)),
    (r"torn|crush|wet|box|arrived damaged|damaged when", ("transit_damage", "high", True, True)),
    (r"colou?r|shade|photo|picture|look", ("color_mismatch", "medium", False, False)),
    (r"wrong", ("wrong_item", "none", False, False)),
    (r"short|length|chart", ("length_shorter_than_chart", "low", False, False)),
    (r"tight|loose|fit|size|small|big|large", ("fit_issue", "none", False, True)),
]


class StubMediaAnalyzer:
    async def analyze(self, media_refs, listing_image_urls, focus):
        out = []
        for ref in media_refs[:MAX_MEDIA]:
            row = query("""SELECT r.comment, r.stated_reason FROM return_media m
                           JOIN returns r ON r.id = m.return_id WHERE m.id = :id""", id=ref)
            if not row:
                out.append(dict(media_id=ref, defect_type=None, severity="none", visible_damage=False,
                                matches_listing=None, description="[stub] media not found"))
                continue
            text_ = f"{row[0]['comment'] or ''} {row[0]['stated_reason']}".lower()
            for pattern, (dtype, sev, dmg, match) in _STUB_RULES:
                if re.search(pattern, text_.replace("_", " ")):
                    out.append(dict(media_id=ref, defect_type=dtype, severity=sev, visible_damage=dmg,
                                    matches_listing=match,
                                    description=f"[stub] {dtype.replace('_', ' ')} (focus: {focus.split(',')[0]})"))
                    break
            else:
                out.append(dict(media_id=ref, defect_type=None, severity="none", visible_damage=False,
                                matches_listing=True, description="[stub] no visible defect"))
        return out


# ───────────── Gemini ─────────────
class _Finding(BaseModel):
    media_id: str
    defect_type: str | None  # snake_case, e.g. sole_separation, stain, torn_fabric, color_mismatch; null if none
    severity: Literal["none", "low", "medium", "high"]
    visible_damage: bool
    matches_listing: bool | None  # null when it cannot be judged
    description: str


PROMPT = """You inspect photos/videos that a customer uploaded with a product return.
Product category focus (what to look for): {focus}

{listing_note}

For EACH customer media file, return one finding. Describe only what is visible; do not guess about
anything you cannot see. Rules:
- defect_type: short snake_case label of the main problem, or null if there is none.
- severity: none | low | medium | high.
- visible_damage: true only if physical damage or wear is visible.
- matches_listing: {matches_rule}
- description: one factual sentence. Do not include any personal information.
Return a JSON array with exactly one finding per customer media_id, in the same order."""

LISTING_NOTE = ("The listing images (what the seller advertised) come first, then the customer's media. "
                "Compare the customer's item with the listing images: same product, color shade, style and details.")
NO_LISTING_NOTE = "No listing images are available, so you cannot compare the item with the listing."
MATCHES_WITH = "true if the customer's item is the product shown in the listing images, false if it differs (wrong item, different color or style), null if you cannot tell."
MATCHES_WITHOUT = "ALWAYS null, because there are no listing images to compare with."


class GeminiMediaAnalyzer:
    def __init__(self):
        self.client = genai.Client(http_options=types.HttpOptions(retry_options=gemini_retry_options(), timeout=40_000))

    @staticmethod
    def _load(media_id: str) -> tuple[bytes, str] | None:
        row = query("SELECT storage_url FROM return_media WHERE id = :id", id=media_id)
        return load_bytes(row[0]["storage_url"]) if row else None

    async def analyze(self, media_refs, listing_image_urls, focus):
        refs = media_refs[:MAX_MEDIA]
        listing = [x for x in (load_bytes(u) for u in listing_image_urls[:MAX_LISTING_IMAGES]) if x]
        parts: list = [types.Part(text=PROMPT.format(
            focus=focus or "general condition",
            listing_note=LISTING_NOTE if listing else NO_LISTING_NOTE,
            matches_rule=MATCHES_WITH if listing else MATCHES_WITHOUT))]
        for i, (data, mime) in enumerate(listing, 1):
            parts += [types.Part(text=f"LISTING image {i} (seller's advertised product):"), types.Part.from_bytes(data=data, mime_type=mime)]
        loaded, missing = [], []
        for ref in refs:
            item = self._load(ref)
            if item is None:
                missing.append(ref)
                continue
            parts += [types.Part(text=f"CUSTOMER media_id: {ref}"), types.Part.from_bytes(data=item[0], mime_type=item[1])]
            loaded.append(ref)
        findings: dict[str, dict] = {}
        if loaded:
            resp, last_err = None, None
            for model in settings.media_models:  # primary, then fallbacks (free-tier quotas are per model)
                try:
                    resp = await self.client.aio.models.generate_content(
                        model=model, contents=[types.Content(role="user", parts=parts)],
                        config=types.GenerateContentConfig(response_mime_type="application/json",
                                                           response_schema=list[_Finding], temperature=0))
                    break
                except Exception as e:
                    last_err = e
            if resp is None:
                raise last_err  # analyze_media() turns this into "media analysis unavailable"
            for f in (resp.parsed or []):
                if f.media_id in loaded:
                    d = f.model_dump()
                    d["severity"] = d["severity"] if d["severity"] in SEVERITIES else "none"
                    if not listing:
                        d["matches_listing"] = None  # cannot be judged without a reference image
                    findings[f.media_id] = d
        for ref in refs:  # one finding per requested file, always
            if ref not in findings:
                reason = "media file unreadable" if ref in missing else "model returned no finding"
                findings[ref] = dict(media_id=ref, defect_type=None, severity="none", visible_damage=False,
                                     matches_listing=None, description=f"Could not analyze: {reason}.")
        return [findings[r] for r in refs]


def get_media_analyzer() -> MediaAnalyzer:
    return StubMediaAnalyzer() if settings.llm_mode == "stub" else GeminiMediaAnalyzer()


async def analyze_media(media_refs: list[str], listing_image_urls: list[str], focus: str) -> dict:
    """Look at the customer's photos/videos (by media id like 'm_123') and compare them with the
    listing images. 'focus' is the category profile's media_focus. Returns one finding per media:
    defect_type, severity (none/low/medium/high), visible_damage, matches_listing, description."""
    try:
        findings = await get_media_analyzer().analyze(media_refs, listing_image_urls, focus)
    except Exception as e:  # media unreadable / backend down: the agent must work from text only
        return {"findings": [], "error": f"media analysis unavailable: {type(e).__name__}: {str(e)[:200]}"}
    return {"findings": findings}
