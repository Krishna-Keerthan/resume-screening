# Phase 1 Plan: Security

Approved inventory and decisions. Read this at the start of every Phase 1 session.
Full route-by-route inventory: `docs/phase1-inventory.md` (gitignored, like `docs/audit.md`).
Line numbers in the inventory are as of commit `71e0043`; re-check before editing.

## Branching
- `fix/phase-0` and `fix/phase-2` are merged into `main` before Phase 1 starts.
- Phase 1 work happens on `fix/phase-1`, branched from `main`.

## Decisions (final)
| ID | Decision |
|---|---|
| D1 | Drop the 3-second refresh grace window entirely. A multi-tab race may log the user out; frontend fix later with `navigator.locks`. |
| D2 | Deleted accounts' emails stay blocked (the unique index covers soft-deleted rows). |
| D3 | Recruiters see a candidate's profile and résumés ONLY if that candidate applied to one of the recruiter's jobs. Grep the frontend for a candidate-browse page: if one exists, `GET /candidates/` lists only `open_to_work=true` candidates with name, headline and skills (no email, phone or résumés); if not, delete `GET /candidates/`. Report which before changing. |
| D4 | Remove `GET /recruiters/` after confirming no frontend caller. |
| D5 | For each duplicate pair (`/scores/rank-candidates` vs `/jobs/<id>/candidates`, `/scores/job-recommendations` vs `/candidates/<id>/recommendations`, `/analytics/*` vs `/recruiters/<id>/analytics\|pipeline`), keep the copy the frontend calls and delete the other. Show grep evidence first. |
| D6 | Drop identity fields (`recruiter_id`, `candidate_id`) from request schemas so `unknown=EXCLUDE` ignores them; identity always comes from `g.jwt_user_id`. Remove them from the frontend in a later commit. |
| D7 | Another user's resource returns 403. Exception: non-active (draft/closed) jobs return 404 to non-owners. Make `rewrite-suggestions` consistent with this. |
| D8 | Migration 0003 includes the email-normalising `UPDATE ... SET email = lower(trim(email))`. |

## Key facts from the inventory
- `require_auth` checks the token signature only and never loads the user, so deleted/deactivated users keep access, and refresh ignores `is_deleted`, so it lasts indefinitely.
- Soft delete sets `is_deleted` but leaves `is_active=True`; almost every check tests only `is_active`.
- Token reuse (`TOKEN_REUSED`) clears the cookie but revokes nothing.
- `assert_owns` has zero call sites; `AuthError` isn't an `AppError`, so raising it gives a 500.
- Email lookups use `ilike` (candidate repo line 26, recruiter repo line 25).
- `RefreshTokenRepository` is unused; auth.py uses the model's session methods. RT-01 comments are false.
- About 125 currently passing tests send no token. Each resource commit updates its own file's tests in the same commit.

## Test harness (first commit, test-only)
- Fixtures: `candidate_a`, `candidate_b`, `recruiter_a`, `recruiter_b` (real rows with password hashes).
- `headers_for(user)` built on `create_tokens`; `anon = {}`.
- Owned objects: `job_a`/`job_b`, `resume_a`/`resume_b`, `application_a` (candidate A applied to job A).
- `check_access(method, url, owner, other, json=None)`: anonymous → 401, other user → 403 (or 404 per D7), owner → 2xx.
- One test that logs in through the real `/auth/login`, so fixtures can't drift from real token issuance.
- Leave existing `sample_*` fixtures alone.

## Batches (one logical fix per commit, failing test first)
1. **Debug block**: remove the cookie-printing block in auth.py (~lines 335-359). Test: the raw refresh token never appears in captured stderr.
2. **Account status** (three commits: login; refresh; require_auth + /me):
   - one predicate: deleted OR inactive = dead;
   - `require_auth` loads the user and returns 401 for dead users;
   - login rejects dead users with the generic `INVALID_CREDENTIALS`;
   - refresh rejects dead users, revokes the token and clears the cookie;
   - deleting an account revokes all its refresh tokens;
   - change-password revokes all other refresh tokens;
   - fix the deleted-candidate visibility bug (`get_with_resumes` doesn't filter `is_deleted`) and the double-delete 204 bug.
   **STOP after batch 2 and report.**
3. **Token reuse**: `TOKEN_REUSED` revokes all the user's tokens and commits; remove the grace window (D1) and its inline `jwt.encode`.
4. **Ownership helper**: register an `AuthError` handler; change `assert_owns` to `assert_owns(resource, user_id, *, owner_attr, message=None)` (required keyword); add `assert_can_view_application`, `assert_can_view_score` and a recruiter→résumé-via-application check. Keep `require_ownership` for self routes. Unit tests.
5. **Routes**, one commit per file, including that file's tests and the D6 schema cleanup, in this order: jobs writes → applications → resumes → scores → analytics → jobs reads/listing. Apply D3, D4, D5, D7. Also: `POST /applications/` rejects inactive jobs and duplicate applications.
6. **Email**: exact lowercase match `func.lower(email) == value.strip().lower()`; migration 0003 with a duplicate pre-check, the D8 update, and unique `lower(email)` indexes on both tables, mirrored in the models.
7. **xfail cleanup**: retarget the 13 create-route tests to `/auth/register/*`, update the 40 that pass with the owner's token, change the 8 "nonexistent → 404" cases to "other user → 403", delete the 10 duplicates/mislabelled tests. Rewrite `TestJobRecommendationsEndpoint::test_returns_200` (it mocks a method the route never calls).
8. **RT-01 refactor**: switch auth.py to `RefreshTokenRepository`; fix or delete the false comments.
9. **Uploads**: Cloudinary résumés private (authenticated delivery, signed short-lived URLs from an ownership-checked endpoint); upload validation: size limit, allowed types, content-based type check.
10. **Rate limiting**: Flask-Limiter (ask before adding the dependency) on login, register and refresh, plus per-user limits on every Groq route: enhance, ai-summary, generate-summary, rewrite-suggestions, analyze, match.

## Small items (fit into the nearest batch)
- `/health/ready` returns a generic error, not `str(exc)`. Report what `/health/services` exposes.
- Check whether the frontend uses trailing slashes; if so, propose `strict_slashes=False`.
- Fix the `_auth_response` docstring during the auth work.
- Remove the dead `actor_id` branch in `PATCH /applications/<id>/stage`.
## Phase 4 notes
- Re-add `location` / `job_type` filters to `POST /scores/job-recommendations` if wanted. The deleted `POST /candidates/<id>/recommendations` accepted them and passed `location_filter` / `job_type_filter` to `JobRecommendationService.recommend`; the kept route passes only `resume` and `top_n`, and the frontend sends only `top_n`.



## Phase 5 notes
- `getResumeDownload` in the frontend client must return `{url}` (the backend sends `{url, expires_in}`; the signed URL is short-lived, so fetch it on click, don't cache it).

## Status and approvals (updated 2026-10-14)
- Batches 1-9 committed on fix/phase-1. Batch 7 complete (2 remaining xfails are intentional Phase 4 scorer markers).
- Approved dependencies: Flask-Limiter, redis client, cloudinary (already added).
- Batch 9 follow-ups still TO DO: (1) DOCX validation counts actual decompressed bytes by streaming; (2) per-worker parse semaphore, default 2; (3) 415 message for nested archives says embedded files aren't supported; (4) smoke script moved to scripts/ and committed; (5) Phase 5 note: getResumeDownload returns {url}.
- Batch 10 TO DO: RATE_LIMIT_STORAGE_URL setting name kept; login limits per IP ("10 per minute") and per IP+email ("5 per minute") plus 30/hour per-email backstop; RATE_LIMIT_REGISTER "10 per hour"; refresh "30 per minute"; RATE_LIMIT_LLM "10 per minute;100 per day" per user on every Groq route incl. POST /applications/ and POST /jobs/; 60/min per user on GET /resumes/<id>/download; ProxyFix x_for=1 with forged-header tests; in_memory_fallback_enabled with error log; production refuses memory://; /health* exempt; Redis service in render.yaml.
- Manual, by the user: run the Cloudinary smoke test with real credentials.