# Supabase Storage smoke test (manual, needs a real project)

**Status: written, not run against a real project.** The automated tests run the backend and this
script against a fake Supabase server (`backend/tests/unit/fake_supabase.py`). They prove which
HTTP calls we make and that the script fails when a bucket is public or a signed URL never expires.
They do not prove that Supabase answers the way the fake does. Run this once per environment before
relying on the storage path, and record the result below.

Use a throwaway Supabase project, or a dedicated private bucket (`resumes-smoke-test`), never real
résumés. Create the bucket **private** (the "Public bucket" switch off) with **no policies** on it;
see `docs/deploy_phase3.md`.

## What it checks

1. The bucket exists and `public` is `false` (read with the service-role key).
2. An upload is accepted and the key is `<32 hex>.pdf`.
3. The plain URLs fail: `.../object/public/<bucket>/<key>` and an unauthenticated read of
   `.../object/<bucket>/<key>`.
4. A signed URL (`signed_url(key, ttl=5)`) returns the original bytes with no credentials.
5. The signed URL stops working after its expiry (it waits `ttl` + 5 s, then fetches again).
6. After `delete(key)` the object is gone: a new signed URL and a download both raise `StorageNotFound`.

## Script

Run from `backend/` in an environment with the dependencies installed:

```bash
export SUPABASE_URL=https://<project>.supabase.co
export SUPABASE_SERVICE_ROLE_KEY=...        # Project Settings -> API; server-side only
export SUPABASE_BUCKET=resumes-smoke-test
python ../scripts/supabase_smoke_test.py
```

It prints one `PASS` / `FAIL` line per step and exits non-zero at the first failure. It never prints
the service-role key, an object key or a signed URL (a signed URL carries a token). The object it
uploads is deleted whatever happens.

## Things the fake could have wrong

If a step fails against the real project, look here first; these are the places the tests rest on the
documented client's behaviour rather than on a real response:

- The headers the Storage API requires. The backend sends `Authorization: Bearer <key>` and `apikey: <key>`.
- The shape of the signed-URL response: the backend reads `signedURL` (a path starting with
  `/object/sign/`) and prefixes `<SUPABASE_URL>/storage/v1`.
- How a missing object is reported: the backend treats HTTP 404, and HTTP 400 with `statusCode` `"404"`,
  as "not found".

## Also check by hand once

- `GET /api/v1/resumes/<id>/download` as the owning candidate returns `{ "url": ..., "expires_in": 300 }`,
  and the URL downloads the file.
- The same call as another candidate returns 403, and as a recruiter without an application returns 403.
- In the Supabase dashboard (Storage), the bucket shows as private and has no policies.

## Result log

| Date | Environment | Who | Steps 1-6 | Notes |
|------|-------------|-----|-----------|-------|
|      |             |     | not run   |       |
