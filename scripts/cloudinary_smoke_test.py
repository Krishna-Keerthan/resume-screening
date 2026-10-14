"""
Manual smoke test for the Cloudinary storage backend. NOT run in CI and not
yet run by anyone: see docs/cloudinary-smoke-test.md.

Run from backend/ with STORAGE_PROVIDER=cloudinary and the CLOUDINARY_* variables set:

    python ../scripts/cloudinary_smoke_test.py
"""
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.getcwd())

from app.services.storage_service import StorageError, StorageService  # noqa: E402

PAYLOAD = b"%PDF-1.4\n% smoke test, safe to delete\n"
TTL = 5


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read()


def must_fail(url: str) -> bool:
    try:
        fetch(url)
    except (urllib.error.HTTPError, urllib.error.URLError):
        return True
    return False


def step(n: int, text: str, ok: bool) -> None:
    print(f"{n}. {'PASS' if ok else 'FAIL'}  {text}")
    if not ok:
        sys.exit(1)


def main() -> None:
    config = {k: os.environ.get(k, "") for k in (
        "STORAGE_PROVIDER", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY",
        "CLOUDINARY_API_SECRET", "CLOUDINARY_FOLDER",
    )}
    storage = StorageService.from_config(config)
    if storage.provider != "cloudinary":
        sys.exit("STORAGE_PROVIDER must be cloudinary")

    result = storage.upload(PAYLOAD, "pdf")
    key = result.key
    step(1, f"uploaded as {key}", key.endswith(".pdf") and "/" in key)

    import cloudinary.utils
    public_url, _ = cloudinary.utils.cloudinary_url(key, resource_type="raw", type="upload", secure=True)
    step(2, "the public (type=upload) URL is refused", must_fail(public_url))

    try:
        url = storage.signed_url(key, ttl=TTL)
        step(3, "a signed URL returns the original bytes", fetch(url) == PAYLOAD)
    except (StorageError, urllib.error.URLError) as exc:
        step(3, f"a signed URL returns the original bytes ({exc})", False)

    time.sleep(TTL + 5)
    step(4, f"the signed URL stops working after {TTL}s (+5s grace)", must_fail(url))

    storage.delete(key)
    time.sleep(2)
    fresh = storage.signed_url(key, ttl=60)
    step(5, "after delete(), a fresh signed URL no longer returns the file", must_fail(fresh))
    print("done")


if __name__ == "__main__":
    main()
