# Cloudinary smoke test (manual, needs real credentials)

**Status: written, not run.** The automated tests only prove which arguments we pass to the Cloudinary
SDK (`type="authenticated"`, `resource_type="raw"`, the signed-URL arguments). Nothing in the repo has
been checked against a real Cloudinary account. Run this once per environment before relying on the
storage path, and record the result below.

Use a throwaway Cloudinary account or a dedicated folder (`CLOUDINARY_FOLDER=smoke-test`), never real résumés.

## What it checks

1. Upload is accepted as `authenticated` + `raw` and the stored key looks like `<folder>/<32 hex>.pdf`.
2. The unsigned delivery URL for that file is refused (not publicly readable).
3. A signed URL from `signed_url(key, ttl=300)` returns the original bytes.
4. The signed URL stops working after its expiry. This is the part most likely to differ from the
   SDK docs: `private_download_url(public_id, "", resource_type="raw", ...)` passes an empty `format`
   for a raw file whose `public_id` already ends in `.pdf`. If step 3 fails, try `format="pdf"` with the
   extension removed from the public_id, and change `CloudinaryStorageBackend.signed_url` accordingly.
5. `delete(key)` removes it (a second download fails).

## Script

Run from `backend/` in an environment with the dependencies installed:

```bash
export STORAGE_PROVIDER=cloudinary
export CLOUDINARY_CLOUD_NAME=...   CLOUDINARY_API_KEY=...   CLOUDINARY_API_SECRET=...
export CLOUDINARY_FOLDER=smoke-test
python ../scripts/cloudinary_smoke_test.py
```

The script is `scripts/cloudinary_smoke_test.py`. It prints one line per step and exits non-zero on the first failure.

## Also check by hand once

- `GET /api/v1/resumes/<id>/download` as the owning candidate returns `{ "url": ..., "expires_in": 300 }`, and the URL downloads the file.
- The same call as another candidate returns 403 and as a recruiter without an application returns 403.
- In the Cloudinary console, the asset shows as *Authenticated* delivery type.

## Result log

| Date | Environment | Who | Steps 1–5 | Notes |
|------|-------------|-----|-----------|-------|
|      |             |     | not run   |       |
