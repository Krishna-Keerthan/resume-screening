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
- Backend deps: `pip install -r requirements.txt` for running the app (what the Dockerfile and `render.yaml` install); add `-r requirements-dev.txt` for tests and `seed.py` (pytest, Faker). Edit the `.in` files and recompile from `backend/`. The `--index-strategy unsafe-best-match` flag is required for the PyTorch CPU extra index:
  - `uv pip compile requirements.in -o requirements.txt --python-version 3.11 --python-platform linux --index-strategy unsafe-best-match --emit-index-url`
  - `uv pip compile requirements-dev.in -c requirements.txt -o requirements-dev.txt --python-version 3.11 --python-platform linux --index-strategy unsafe-best-match`
- Backend tests: `cd backend && pytest -q` (needs the dev deps)
- Seed data: `cd backend && python seed.py` (needs the dev deps, because it imports Faker)
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

## Design rules (SOLID and DRY)

These apply to all new and changed code. Old code that breaks them is listed in Phase 4b and fixed there, one logical change per commit. Do not fix it opportunistically inside an unrelated change.

Single responsibility

A route does four things only: parse input, check auth/ownership, call one service, serialise the result. No business logic, no queries, no scoring in routes.
Services never import Flask's request/g/current_app. Repositories contain queries only. Models contain no business rules beyond their own invariants.
Size limits (report-only until Phase 4b finishes, then enforced): function at most 40 lines, module at most 400 lines, cyclomatic complexity at most 10.

Open/closed

Add behaviour by adding an implementation, not by adding a branch. Storage backends (Cloudinary, local) sit behind one interface and are chosen in exactly one factory. if provider == ... is forbidden outside that factory. The same applies to scorers and any other pluggable part.

Liskov

Every implementation of an interface returns the same types and raises the same exceptions. Contract tests run against every implementation (both storage backends, for example).

Interface segregation

Depend on the narrowest thing you need: pass a service or a small protocol, not the whole Services container. get_services() is for route setup only, never inside services.

Dependency inversion

Services receive their dependencies through the factory. No Repo() construction inside route or service bodies, no function-level imports of concrete classes to dodge a cycle (fix the cycle instead), no MagicMock fallbacks.
Do not add an interface for a single implementation unless a test seam needs it. An abstraction nobody uses is its own violation.

DRY means one source of truth per piece of knowledge, not deduplicated text

One place for each of: score thresholds and labels, stage transitions, enum display labels, ownership rules, error codes, pagination, serialisation, "active résumé" logic, config defaults. Frontend API types are generated from the backend OpenAPI schema.
Before writing a helper, grep for an existing one. If the same rule now exists twice, extract it in the same commit.
Two pieces of code that look alike but change for different reasons are not duplicates. Do not merge them.

Enforcement (added in Phase 4b, dev-only, report-only first, then gating)

import-linter: layering api → services → repositories → models, with core/ and utils/ below them and no upward imports.
ruff: complexity, length and unused-code rules.
jscpd: duplicate-code detection over backend and frontend, with a fail threshold once the refactor brings the number down.
ESLint with Next's defaults, plus an npm run lint script.
Never weaken a rule or raise a threshold to make a check pass. Report the violation instead.

## Dependency policy
Every dependency has exactly one job, recorded in docs/stack.md (technology, its single job, where it's used, what it overlaps with, keep/remove verdict).
Adding a dependency needs one line in docs/stack.md first: purpose, what existing tool cannot do it, why. Two libraries for the same job are not allowed; one gets removed.
Dev-only tools go in requirements-dev.in or devDependencies, never in production images.
Remove a dependency in its own commit with proof: grep shows no use, the full suite passes on SQLite and Postgres, the frontend builds, and the Docker image still boots.

## Definition of done (per task)
- [ ] Failing test written and shown failing
- [ ] Fix applied
- [ ] Full backend suite passes (paste the summary line)
- [ ] Frontend typecheck passes if frontend touched
- [ ] No new FIX comments, debug prints or unused code
- [ ] Short summary: what changed, which files, what you did NOT verify

## Current work

Phases 0, 0.5, 1 and 2 are done and merged to main (tag phase-1-done). Current phase: Phase 3 (deploy wiring) on fix/phase-3. Planned order after it: Phase 4b (stack and design audit and refactor), then Phase 4 (scoring), Phase 5 (frontend contract), Phase 6 (hardening). At the start of every session read docs/phase1_plan.md (security decisions that still apply), docs/deploy_phase3.md once it exists, and repair-playbook.md. Do not re-decide settled questions; ask if something conflicts.