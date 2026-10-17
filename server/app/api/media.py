from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.config import settings
from app.services.storage import ALLOWED, EXT_INFO, storage

router = APIRouter(prefix="/media", tags=["media"])


class UploadUrlIn(BaseModel):
    content_type: str


class UploadUrlOut(BaseModel):
    upload_url: str
    method: str = "PUT"
    storage_url: str  # media path; send it back in POST /returns
    expires_in: int


@router.post("/upload-url", response_model=UploadUrlOut)
def create_upload_url(body: UploadUrlIn):
    """Signed URL for one photo/video. The browser PUTs the file there directly."""
    if body.content_type not in ALLOWED:
        raise HTTPException(415, f"Unsupported type. Allowed: {', '.join(ALLOWED)}")
    key = storage.new_key(body.content_type)
    url, ttl = storage.signed_upload_url(key)
    return UploadUrlOut(upload_url=url, storage_url=key, expires_in=ttl)


@router.put("/local/{key:path}", status_code=201)
async def upload_local(key: str, request: Request, exp: int, sig: str):
    """Local stand-in for the Cloud Storage signed upload. Removed when GCS is wired in."""
    if not storage.verify(key, exp, sig):
        raise HTTPException(403, "Invalid or expired upload URL")
    ext = key.rsplit(".", 1)[-1]
    if ext not in EXT_INFO:
        raise HTTPException(415, "Unsupported file type")
    ctype, mtype = EXT_INFO[ext]
    if request.headers.get("content-type", "").split(";")[0] != ctype:
        raise HTTPException(415, f"Content-Type must be {ctype}")
    limit = settings.max_video_bytes if mtype == "video" else settings.max_photo_bytes
    if int(request.headers.get("content-length", 0)) > limit:
        raise HTTPException(413, f"File too large (max {limit // (1024 * 1024)} MB)")
    data = await request.body()
    if len(data) > limit:
        raise HTTPException(413, f"File too large (max {limit // (1024 * 1024)} MB)")
    storage.save(key, data)
    return {"storage_url": key, "size_bytes": len(data)}


@router.get("/local/{key:path}")
def view_local(key: str):
    """Lets the review screen display uploaded media (local only)."""
    if not storage.exists(key):
        raise HTTPException(404, "Not found")
    return FileResponse(storage.path(key))
