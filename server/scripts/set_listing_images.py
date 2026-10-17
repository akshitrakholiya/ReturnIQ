"""Attach listing (seller) images to a product, or clear them.

    python -m scripts.set_listing_images --product "TrailRun Sneakers" front.jpg side.jpg
    python -m scripts.set_listing_images --product p_6 --urls https://example.com/a.jpg https://example.com/b.jpg
    python -m scripts.set_listing_images --product p_6 --clear

Local files are copied into media_uploads/listings/<product id>/ and stored as their media path
(listings/<product id>/<n>.jpg). --urls stores external https:// URLs as they are.
"""
import argparse
import mimetypes
import shutil
import sys
from pathlib import Path

from sqlalchemy import text

from app.db.session import engine
from app.services.storage import ALLOWED, storage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True, help="product id (p_6) or exact name")
    ap.add_argument("--clear", action="store_true", help="remove all listing images")
    ap.add_argument("--urls", nargs="*", help="https:// image URLs to store as they are")
    ap.add_argument("images", nargs="*", help="local image files (jpg/png/webp)")
    a = ap.parse_args()

    with engine.begin() as c:
        p = c.execute(text("SELECT id, name FROM product WHERE id = :x OR name = :x"), {"x": a.product}).first()
        if not p:
            sys.exit(f"No product '{a.product}'")
        urls: list[str] = []
        for u in a.urls or []:
            if not u.startswith("https://"):
                sys.exit(f"Only https:// URLs are accepted: {u}")
            urls.append(u)
        dest = Path(storage.root) / "listings" / p.id
        if dest.exists():
            shutil.rmtree(dest)  # replacing: drop the old files
        for i, f in enumerate(a.images, 1):
            ctype = mimetypes.guess_type(f)[0]
            if ctype not in ALLOWED or not ctype.startswith("image/"):
                sys.exit(f"Not a supported image: {f}")
            dest.mkdir(parents=True, exist_ok=True)
            name = f"{i}.{ALLOWED[ctype][0]}"
            shutil.copyfile(f, dest / name)
            urls.append(f"listings/{p.id}/{name}")
        if not a.clear and not urls:
            sys.exit("Give image files, --urls, or --clear")
        c.execute(text("UPDATE product SET listing_image_urls = :u, report_stale = true, updated_at = now() WHERE id = :id"),
                  {"u": urls, "id": p.id})
    print(f"{p.name} ({p.id}) listing images -> {urls or 'none'}")


if __name__ == "__main__":
    main()
