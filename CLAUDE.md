# CLAUDE.md

AI Resume Screening & Job Recommendation Platform (ATS).
We are in a **repair phase**: no new features until the audit items are fixed.

## Stack
- **Backend** (`backend/`): Flask 3, SQLAlchemy 2, layered as `api/` → `services/` → `repositories/` → `models/`. JWT auth (access token + HttpOnly refresh cookie). Scoring = BM25 + MiniLM embeddings + experience score + section-quality score. Groq (Llama 3.1) for summaries/tips. Cloudinary or local disk for files.
- **Frontend** (`frontend/`): Next.js 16 App Router, TanStack Query, Zustand, Tailwind, Recharts. Separate candidate and recruiter areas.
- **Infra**: Docker Compose, Render blueprint, Procfile. Alembic for migrations.

## Commands
<!-- Adjust these if your paths/scripts differ -->
- The backend lock file (`backend/requirements.txt`) is Linux-only, so run the backend and its tests via Docker or WSL, not native Windows.
- Backend tests: `cd backend && pytest -q`
- Single test: `cd backend && pytest -q path/to/test_file.py::test_name`
- Frontend typecheck: `cd frontend && npx tsc --noEmit`
- Frontend lint: `cd frontend && npm run lint`
- Frontend build: `cd frontend && npm run build`

## Non-negotiable rules
1. **Prove every fix.** For every bug: write a test that fails first, then fix, then run the full backend suite. Show me the before/after test output. A fix without a failing-then-passing test is not done.
2. **Never write "FIX XX-NN" or "fixed" comments.** The commit message describes the fix. If you find an existing FIX comment that is false, delete it or correct it.
3. **Never claim something is done without running it.** If you could not run a command, say so explicitly.
4. **Small, reviewable changes.** One logical fix per commit. Do not refactor unrelated code in the same change.
5. **Stop and ask** before: changing the database schema, changing auth/token logic beyond the stated task, deleting files, or adding a new dependency.

## Security rules
- Every write route and every private-read route must use `@require_auth` **and** an ownership check (the resource belongs to the current user, or the user has the right role).
- Identity comes **only from the token**. Never trust `recruiter_id`, `candidate_id` or `user_id` from the request body or query string.
- Users with `is_deleted=True` or `is_active=False` must be rejected by login, refresh and every authenticated route.
- Never log tokens, cookies, passwords or full résumé contents. No debug print blocks.
- Every new protected route needs tests for: no token → 401, another user's resource → 403 (or 404), owner → success.

## Code conventions
- Enums: compare and serialise with `.value`. Never use `str(enum)` or put an enum directly in an f-string.
- JSON columns: use `JSON().with_variant(JSONB, "postgresql")` so tests run on SQLite. Store real dicts/lists, never pre-`json.dumps`-ed strings.
- Config: read settings from one place (Flask config populated from `config/settings.py`). If you add a setting, it must actually be used.
- Score thresholds/labels live in **one** config value shared by backend and frontend. Do not hardcode 0.8/0.65/0.5 anywhere else.
- External calls (Groq, Cloudinary) must report failure honestly. A fallback response must not set `llm_enhanced=True`.
- Frontend types for API responses should be generated from the backend OpenAPI schema, not hand-written.

## Definition of done (per task)
- [ ] Failing test written and shown failing
- [ ] Fix applied
- [ ] Full backend suite passes (paste the summary line)
- [ ] Frontend typecheck passes if frontend touched
- [ ] No new FIX comments, debug prints or unused code
- [ ] Short summary: what changed, which files, what you did NOT verify