"""
Manual smoke test for the Supabase storage backend. NOT run in CI. Its logic is tested
against a fake server (backend/tests/unit/test_supabase_smoke_script.py), but only a run
against a real project shows Supabase behaves as the backend expects: see
docs/supabase-smoke-test.md.

Run from backend/ with the three variables set (use a throwaway project or a dedicated
private bucket, never real résumés):

    export SUPABASE_URL=https://<project>.supabase.co
    export SUPABASE_SERVICE_ROLE_KEY=...
    export SUPABASE_BUCKET=resumes-smoke-test
    python ../scripts/supabase_smoke_test.py

It prints one PASS/FAIL line per step and exits non-zero at the first failure. It never
prints the service-role key, an object key or a signed URL (they carry a token).
"""
import os
import re
import sys
import time

sys.path.insert(0, os.getcwd())

import httpx  # noqa: E402

from app.services.storage_service import StorageError, StorageNotFound, SupabaseStorageBackend  # noqa: E402

PAYLOAD = b"%PDF-1.4\n% smoke test, safe to delete\n"
TTL_SECONDS = 5
GRACE_SECONDS = 5
VARIABLES = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_BUCKET")


def run(config: dict, *, transport=None, sleep=time.sleep, report=print) -> bool:
    """Run the checks against the project in `config`; True if every one passed."""
    base = f"{config['SUPABASE_URL'].rstrip('/')}/storage/v1"
    bucket = config["SUPABASE_BUCKET"]
    storage = SupabaseStorageBackend(
        config["SUPABASE_URL"], config["SUPABASE_SERVICE_ROLE_KEY"], bucket, transport=transport)
    http = httpx.Client(timeout=30, transport=transport)

    def get(url, headers=None):
        try:
            return http.get(url, headers=headers or {})
        except httpx.HTTPError:
            return None

    def serves(response, payload=PAYLOAD) -> bool:
        return response is not None and response.status_code == 200 and response.content == payload

    results = []

    def step(text: str, ok: bool) -> bool:
        results.append(ok)
        report(f"{len(results)}. {'PASS' if ok else 'FAIL'}  {text}")
        return ok

    try:
        private = storage.bucket_is_private()
    except StorageError:
        private = False
    if not step("the bucket exists and is private (public is false)", private):
        return False

    key = storage.upload(PAYLOAD, "pdf").key
    try:
        if not step("uploaded under a random key (32 hex + .pdf)", re.fullmatch(r"[0-9a-f]{32}\.pdf", key) is not None):
            return False

        plain = get(f"{base}/object/public/{bucket}/{key}")
        unauthenticated = get(f"{base}/object/{bucket}/{key}")
        if not step("the plain URLs fail: public URL and an unauthenticated read",
                    not serves(plain) and not serves(unauthenticated)):
            return False

        url = storage.signed_url(key, ttl=TTL_SECONDS)
        if not step("a signed URL returns the original bytes, without any credentials", serves(get(url))):
            return False

        sleep(TTL_SECONDS + GRACE_SECONDS)
        if not step(f"the signed URL stops working after {TTL_SECONDS}s (+{GRACE_SECONDS}s grace) and does not expire",
                    not serves(get(url))):
            return False
    finally:
        storage.delete(key)

    try:
        storage.signed_url(key, ttl=60)
        gone = False
    except StorageNotFound:
        gone = True
    try:
        storage.download_bytes(key)
        gone = False
    except StorageNotFound:
        pass
    return step("after delete(), the object is gone: no signed URL and no download", gone)


def main() -> None:
    config = {name: os.environ.get(name, "") for name in VARIABLES}
    missing = [name for name, value in config.items() if not value]
    if missing:
        sys.exit("Set these environment variables: " + ", ".join(missing))
    if not run(config):
        sys.exit(1)
    print("done")


if __name__ == "__main__":
    main()
