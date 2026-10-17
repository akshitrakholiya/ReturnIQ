"""Media storage. LocalStorage today; a GcsStorage with the same methods replaces it
when the Google Cloud project exists (signed URL via blob.generate_signed_url).

The database stores only the media path inside the storage, e.g. 'returns/P09/r_172/r_172_defect.jpg'.
Where that path lives (local folder or bucket) and the URL to show it are decided here from config,
so moving to Cloud Storage changes config, not data. A full https:// URL is kept as is: only listing
images set by scripts/set_listing_images.py can be external."""
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


LEGACY_PREFIX = "local://"  # older rows stored 'local://<path>'; still read, never written


class LocalStorage:
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

    def key(self, stored: str) -> str | None:
        """Stored value -> media path in our storage, or None for an external URL or an invalid path."""
        if stored.startswith(LEGACY_PREFIX):
            stored = stored[len(LEGACY_PREFIX):]
        if not stored or "://" in stored or stored.startswith(("/", "\\")):
            return None
        try:
            self.path(stored)
        except ValueError:
            return None
        return stored

    def view_url(self, stored: str) -> str:
        """URL the browser can show. Built at read time, never stored (a GCS signed URL expires)."""
        key = self.key(stored)
        return f"{settings.public_base_url}/media/local/{key}" if key else stored

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
    """Fetch an image/video by its stored value -> (bytes, mime type), or None if it cannot be read.

    media path -> file in our storage (customer uploads, listing images)
    https://   -> downloaded (external listing images; written by our scripts, never by customers)
    """
    key = storage.key(url)
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
