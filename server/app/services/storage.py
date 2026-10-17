"""Media storage. LocalStorage today; a GcsStorage with the same methods replaces it
when the Google Cloud project exists (signed URL via blob.generate_signed_url)."""
import hashlib
import hmac
import time
import uuid
from pathlib import Path

import httpx

from app.core.config import settings

# content type -> (extension, media type stored in return_media.type)
ALLOWED = {
    "image/jpeg": ("jpg", "photo"),
    "image/png": ("png", "photo"),
    "image/webp": ("webp", "photo"),
    "video/mp4": ("mp4", "video"),
    "video/quicktime": ("mov", "video"),
}
EXT_INFO = {ext: (ctype, mtype) for ctype, (ext, mtype) in ALLOWED.items()}


class LocalStorage:
    scheme = "local://"

    def __init__(self):
        self.root = Path(settings.media_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ── keys and paths ──
    def new_key(self, content_type: str) -> str:
        return f"uploads/{uuid.uuid4().hex}.{ALLOWED[content_type][0]}"

    def path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:  # blocks ../ traversal
            raise ValueError("invalid media key")
        return p

    def storage_url(self, key: str) -> str:
        return self.scheme + key

    def key_from_url(self, storage_url: str) -> str | None:
        return storage_url[len(self.scheme):] if storage_url.startswith(self.scheme) else None

    def view_url(self, storage_url: str) -> str:
        key = self.key_from_url(storage_url)
        return f"{settings.public_base_url}/media/local/{key}" if key else storage_url

    # ── signed upload URL (HMAC + expiry) ──
    def _sig(self, key: str, exp: int) -> str:
        msg = f"{key}|{exp}".encode()
        return hmac.new(settings.media_signing_secret.encode(), msg, hashlib.sha256).hexdigest()

    def signed_upload_url(self, key: str) -> tuple[str, int]:
        exp = int(time.time()) + settings.upload_url_ttl_seconds
        url = f"{settings.public_base_url}/media/local/{key}?exp={exp}&sig={self._sig(key, exp)}"
        return url, settings.upload_url_ttl_seconds

    def verify(self, key: str, exp: int, sig: str) -> bool:
        return exp >= time.time() and hmac.compare_digest(sig, self._sig(key, exp))

    # ── file operations ──
    def save(self, key: str, data: bytes) -> None:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def exists(self, key: str) -> bool:
        try:
            return self.path(key).is_file()
        except ValueError:
            return False

    def size(self, key: str) -> int:
        return self.path(key).stat().st_size


storage = LocalStorage()


MAX_LISTING_IMAGES = 3
_MAX_REMOTE_BYTES = 10 * 1024 * 1024


def load_bytes(url: str) -> tuple[bytes, str] | None:
    """Fetch an image/video by its stored URL -> (bytes, mime type), or None if it cannot be read.

    local://  -> files under media_dir (customer uploads, locally stored listing images)
    https://  -> downloaded (listing images from the dataset; written by our own pipeline, never by customers)
    gs://     -> not wired yet; returns None until Cloud Storage replaces LocalStorage
    """
    key = storage.key_from_url(url)
    if key is not None:
        if not storage.exists(key):
            return None
        info = EXT_INFO.get(key.rsplit(".", 1)[-1])
        return (storage.path(key).read_bytes(), info[0]) if info else None
    if url.startswith("https://"):
        try:
            r = httpx.get(url, timeout=10, follow_redirects=True)
            mime = r.headers.get("content-type", "").split(";")[0]
            if r.status_code == 200 and mime in ALLOWED and len(r.content) <= _MAX_REMOTE_BYTES:
                return r.content, mime
        except httpx.HTTPError:
            pass
    return None
