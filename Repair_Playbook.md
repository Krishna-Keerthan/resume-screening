# Repair Playbook — Claude Code prompts

How to use:
- Put `CLAUDE.md` in the repo root and the audit report at `docs/audit.md`.
- Start a **fresh Claude Code session per phase** (`/clear` between phases).
- Work on a branch per phase: `git checkout -b fix/phase-0`.
- Use plan mode (Shift+Tab) for the first prompt of each phase. Approve the plan before edits.
- After each phase: read the diffs, run the checks listed, merge, tag (`git tag phase-0-done`).

---

## Phase 0 — Make the test suite runnable (½ day)

**Prompt 1 (plan):**
> Read CLAUDE.md and docs/audit.md. Our test suite shows 3 failed, 4 passed, 369 errors because `Resume` uses PostgreSQL JSONB which SQLite can't create (backend/app/models/resume.py:69-76). Plan how to: (1) replace JSONB with `JSON().with_variant(JSONB, "postgresql")` everywhere in models, (2) fix the 3 outdated config tests, (3) re-save requirements.txt as UTF-8, remove Windows-only pins (mkl, tbb, intel-openmp) and packages the code never imports (verify each with grep before removing). Don't edit yet — show the plan and the grep evidence.

**Prompt 2 (do):**
> Apply the plan. Run the full backend suite and paste the summary line. List any tests still failing with a one-line reason each. Do not fix those yet.

**Check yourself:** `pytest -q` errors drop from 369 to ~0. Failures that remain are real bugs, which is good. `pip install -r requirements.txt` works in a clean Linux venv/Docker.

---

## Phase 1 — Security (1–1½ days)

**Prompt 1 (inventory):**
> List every route in backend/app/api/v1/ as a table: method, path, current auth decorator (or none), whether it reads identity from token or from request body/query, and what ownership rule it SHOULD have. Don't edit anything.

*Review this table yourself. It's the most important artefact of the whole repair.*

**Prompt 2 (test harness):**
> Add test fixtures for: an authenticated candidate, a second candidate, an authenticated recruiter, a second recruiter, and an unauthenticated client. Then write tests (expected to fail now) for every route in the table: no token → 401, other user's resource → 403/404, owner → success. Run them and show how many fail.

**Prompt 3 (fix, in batches):**
> Fix auth for jobs.py and resumes.py only: add @require_auth, ownership checks, and take recruiter_id/candidate_id from the token, never the body. Run the suite and show the summary.

Repeat Prompt 3 for: `applications.py` → `scoring.py` → `analytics.py` → remaining files.

**Prompt 4 (auth internals):**
> Fix these in auth, each with a test first: (a) delete the TEMPORARY DEBUG block at auth.py:354-378; (b) login, refresh and profile must reject is_deleted users; (c) on TOKEN_REUSED, revoke the whole token family and make the 3-second grace window not issue a new access token to the reused token; (d) apply rate limiting to login using the existing RATE_LIMIT_* settings via Flask-Limiter (ask before adding the dependency).

**Prompt 5 (storage):**
> Change Cloudinary résumé uploads from public raw to authenticated/private, and serve downloads through a signed short-lived URL from an authenticated endpoint that checks ownership (candidate owns it, or recruiter has an application linked to it). Tests first.

**Check yourself:** re-run the audit's curl probe. Unauthenticated POST/PATCH/DELETE on /jobs → 401. Deleted candidate login → 401/403. `grep -rn "print(" backend/app` shows no token printing.

---

## Phase 2 — Crash bugs (½ day)

**Prompt:**
> Fix each of these with a failing regression test first, one commit each:
> 1. `repo.list_all()` missing on Job and Application repositories (jobs.py:62, applications.py:87)
> 2. `soft_delete` on Recruiter, which has no soft-delete support (recruiters.py:159). Add proper soft delete; jobs must NOT be hard-deleted via cascade.
> 3. `recommend(location=…, job_type=…)` wrong arg names (candidates.py:457)
> 4. `score_raw(job_required_years=…)` wrong arg name (scoring.py:105); remove the false SC-01 comment
> 5. sequential fallback called without `resume_oov` (ats_scorer.py:405, 462)
> 6. STORAGE_PROVIDER and CLOUDINARY_* never reach Flask config (storage_service.py:76 vs config/settings.py); add cloudinary to requirements
> 7. service_factory.py:142 reads non-existent ATS_SCORE_WEIGHTS; use the WEIGHT_* settings
> Show the suite summary after each.

**Check yourself:** the four 500s in the audit's probe table now return 200/204.

---

## Phase 3 — Deploy wiring (2–3 days, the slowest part)

**Prompt 1:**
> Fix the double /api/v1: docker-compose.yml:69-70 sets URLs ending in /api/v1 and lib/api/client.ts:171 appends it again. Pick one convention (base URL WITHOUT /api/v1) and update compose, .env.example, Render blueprint, and client.ts. Also make client.ts not throw at import time when INTERNAL_API_URL is missing; fall back to NEXT_PUBLIC_API_URL with a clear console warning.

**Prompt 2:**
> Set up Alembic properly: create the migrations/ folder, remove it from .gitignore, generate an initial migration from the current models, and replace create_all() in production startup with `alembic upgrade head`. Show me the generated migration before committing.

**Prompt 3 (decide first, then prompt):**
Pick ONE cookie strategy before prompting:
- **(A) Same parent domain:** `app.yourdomain.com` (Vercel) + `api.yourdomain.com` (Render), cookie `Domain=.yourdomain.com; SameSite=Lax; Secure`. Needs a custom domain.
- **(B) Next.js proxy:** frontend calls `/api/*` on its own domain; `next.config` rewrites to Render. Cookie becomes first-party. No custom domain needed.

> Implement cookie strategy [A or B]. Update the refresh cookie settings in auth.py, the Next middleware cookie check, and CORS. Explain what I need to configure manually in Vercel/Render.

**Prompt 4:**
> Unify server entry point and timeouts: one entry (wsgi:app) for Docker, Procfile and Render, with the same timeout. Make the embedding model load once using gunicorn --preload. Make the JWT TTL, DB_POOL_*, GROQ_MAX_RETRIES, CORS_MAX_AGE and LOG_LEVEL env vars actually take effect, or delete the ones we don't need.

**Check yourself (manually):** deploy to Render + Vercel, log in, hard-reload a protected page (session survives), upload a résumé, redeploy the backend (file still there), check the Render logs for no tokens.

---

## Phase 4 — Scoring & data integrity (1½–2 days)

**Prompt 1:**
> Scoring cache fixes, tests first: (a) add a `force` parameter to score_resume_job (ats_scorer.py:155) and use it from "Refresh Score"; (b) invalidate stored scores when a résumé or job is edited; (c) when a candidate applies and a score already exists, attach it to the application.

**Prompt 2:**
> Correctness fixes, tests first: (a) win-rate stage comparison at candidates.py:518 — use .value everywhere and grep for other str(enum) usages; (b) hiring recommendation should be able to return "no" for weak candidates (explainability_engine.py:335); (c) candidate ranking reads non-existent candidate.experience_years; (d) total_applications_scored counts the wrong thing; (e) unrecognised-skill tips iterate over a JSON string (resume_analysis_service.py:244); (f) missing-skills aggregation double-counts; (g) withdraw must be idempotent and not decrement applicant_count twice.

**Prompt 3:**
> Skill parser: add an alias map (Postgres→PostgreSQL, K8s→Kubernetes, ReactJS→React, sklearn→scikit-learn, etc.) and word-boundary matching. Treat ambiguous short skills (c, r, go, rest, move, express) as matches only in a skills section or with context. Add tests for both true and false positives.

**Prompt 4:**
> Stop overwriting recruiter input: keep the recruiter's skills and description as the source of truth; store parsed skills and the AI rewrite as suggestions the recruiter can accept. Make Groq failures report failure (llm_enhanced=False, no fake summary). Fix double-encoded JSON storage and normalise contact_info to always be a dict, with a data migration for existing rows.

---

## Phase 5 — Frontend ↔ backend contract (1–1½ days)

**Prompt 1:**
> Make the backend expose an accurate OpenAPI schema from Pydantic response models for every endpoint the frontend uses. Then add openapi-typescript to the frontend, generate types, and replace the hand-written API interfaces. Run `npx tsc --noEmit` and list every type error. Those are the contract mismatches.

**Prompt 2:**
> Fix each type error. Known ones: RankedCandidate rank/candidate_name, top_missing_skills vs most_common_missing, avg_score vs avg_ats_score, sessions_revoked vs revoked_sessions, pipeline card score breakdown, experience dates, projects shape. Move score label thresholds to a single backend config value exposed via an endpoint, and remove the copy in scoreColors.ts. Make the pipeline page use backend stage-transition rules; recruiters must not be offered "withdrawn".

**Prompt 3:**
> Fix the frontend bugs: Generate-summary button never appears; recruiter job search does nothing; drafts invisible without a status filter; ~20 parallel score previews on jobs page load (batch or lazy-load); `{job.experience_years && …}` renders "0"; redirect to login after password change instead of the dashboard.

**Check yourself:** click through every candidate and recruiter page. No NaN, #undefined or empty skill-gap panels.

---

## Phase 6 — Optional hardening (2–3 days)
- Background jobs for parsing, scoring and LLM calls with RQ + Redis
- GitHub Actions CI: backend tests, frontend typecheck and build on every push
- Health check endpoint and structured logging
- Clean up: dead code (response schemas, utils/pagination.py, validators.py, unused components), stale README, seed script password and seed_report.md
- Close the direct-backend bypass: Vercel adds a shared-secret header to proxied requests and the backend rejects (or ignores X-Forwarded-For from) requests without it. Today anyone calling the *.onrender.com address directly skips Vercel and, with two trusted hops, chooses their own rate-limit key (see docs/deploy_phase3.md).

---

## Final step — portfolio write-up
> Write a "Production hardening" section for the README: before/after test counts, security issues fixed, the contract-type generation approach, and deployment architecture. Keep it factual, under 300 words.