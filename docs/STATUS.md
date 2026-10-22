# Project status (resume screening platform repair)

Last updated: 2026-10-22, from reports in the planning chat. Git is the source of truth: if this file and `git log` disagree, believe git and fix this file. Update it at the end of every session.

## Verify first (a fresh session must run these before trusting anything below)
- `git status`, `git branch -a`, `git tag`
- `git log --oneline main..fix/phase-3 | wc -l` (last reported: 46-48 commits ahead) and `git log --oneline fix/phase-3..main` (should print nothing)
- Is `Repair_Playbook.md` still capitalised? CLAUDE.md refers to `repair-playbook.md`.

## Done
- Phase 0, 0.5, 2 (test baseline, crash bugs, Alembic) and Phase 1 (security: every route authenticated and ownership-checked, atomic refresh rotation, rate limiting, private uploads, route-guard test). Tagged `phase-1-done`.
- Phase 3 code on `fix/phase-3`: Vercel proxy and first-party refresh cookie (strategy B); `alembic upgrade head` in the start command; storage moved from Cloudinary to Supabase Storage behind one interface (no public URLs); Postgres moved to the Supabase session pooler (migration 0005 revokes anon/authenticated privileges); liveness check that makes no dependency calls; Groq shared time budget; one gunicorn config; model baked into the build.
- Last known suites (2026-10-19): Postgres 16: 1059 passed, 6 skipped, 2 xfailed. SQLite: 1053 passed, 12 skipped, 2 xfailed. The 2 xfails are intentional Phase 4 scorer markers.

## Decisions (settled; do not re-ask)
- Cookie strategy B (Next.js proxy). TRUSTED_PROXY_HOPS=2 is an estimate until checked on the real deployment, then remove the temporary proxy-chain logging in its own commit.
- Supabase for Storage and Postgres. Supabase Auth is NOT used (own JWT login). Session pooler on port 5432; production refuses port 6543.
- Data API: disable it. Test the order on a throwaway project first: storage smoke test, disable Data API, storage smoke test again. Only then repeat on the real project. RLS stays off for now (revokes in 0005 are the defence).
- `/health/ready` reports storage reachability but does not return 503 for it. Render's healthCheckPath is the liveness endpoint (Render restarts a running service after 60 s of failed checks).
- One gunicorn worker in production. Free and Starter are 512 MB; Starter adds CPU, not memory. Standard is 2 GB.
- Accepted residual: calling the onrender.com address directly bypasses Vercel (fix = shared-secret header, Phase 6). No git history rewrite.
- Design rules and dependency policy are in CLAUDE.md. Never print keys or connection strings.

## Measurements (docker, approximates Render; not Render)
- Anonymous memory about 351 MiB in every run; no OOM kill from 512m down to 384m (production-like: Postgres, Redis, fake Supabase). Page cache explains peak swings of up to about 150 MiB.
- At 0.1 CPU the port opens only after 69-75 s (torch and model load with preload); requests in that window are refused. First scoring about 2 s, later about 100 ms. At 0.5 CPU boot was about 15 s.
- Unmeasured: Render's own memory accounting, real Supabase over TLS, cold start after idle on Render, proxy upload limits.

## Manual steps (the user's; Claude Code cannot do these)
1. Throwaway Supabase project, private bucket, credentials only in a local gitignored `.env`.
2. Run the Supabase checks (docs/supabase_checks.md or docs/supabase-smoke-test.md: reconcile to one file): DB integration test, storage smoke test, then both again with the Data API disabled. Send back pass/fail lines and counts only.
3. First deploy to Free following docs/deploy_phase3.md. Record: live message, port detection, memory graph and any "Out of memory!", first request after 15+ idle minutes, proxy-chain log line, the 429 test from a phone on mobile data, résumé survives a redeploy, uploads of about 9 MB and 10.5 MB, no tokens or cookies in logs.

## Next engineering
- Fix the memory note in docs/stack.md (anonymous memory vs PSS) and the boot-time breakdown; a startup design proposal (open the port early, load the model in a background thread) is awaiting approval. Do not implement before Render numbers exist.
- Then merge Phase 3, tag `phase-3-code`.
- Phase 4b (measure first): stack audit (docs/stack.md), DRY (jscpd), SOLID (import-linter, ruff), ESLint and an `npm run lint` script; PyMuPDF vs pdfplumber overlap; Zustand vs TanStack Query; axios vs fetch; Tailwind 3 to 4 (7 audit findings in the Tailwind 3 chain).
- Phase 4 (scoring): cached scores refresh and link to applications, win-rate enum bug, hiring recommendation can't say "no", BM25 one-document bug, B.Tech/BE degree regex, skill aliases, recruiter input overwritten, Groq failures must say failed (and skipped vs failed vs not needed), JSON columns double-encoded, withdraw idempotent, re-add location/job_type filters if wanted.
- Phase 5 (frontend contract): OpenAPI-generated types, field mismatches, one score-threshold source, remove identity fields the backend now ignores, getResumeDownload returns {url}, multi-tab refresh via navigator.locks.
- Phase 6: verify-full SSL with Supabase's CA, shared-secret header, CI (tests on Postgres), background jobs, subprocess for parse timeouts, cleanup.