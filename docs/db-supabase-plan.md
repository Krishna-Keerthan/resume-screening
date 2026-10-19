# Plan: Postgres on Supabase (and storage follow-ups)

Decision (user, Oct 2026): Postgres moves from Render to Supabase; storage already moved from Cloudinary to Supabase Storage. Supabase Auth is NOT adopted (the app has its own JWT login).
Read CLAUDE.md first. Never print or log a connection string or key; local credentials live only in a gitignored `.env`. Report verified and not verified separately.

## Facts checked against vendor docs (Oct 2026)
Supabase connections
- Direct connections use IPv6 by default. The shared pooler is IPv4-only on every plan, in both session and transaction mode (current docs). Session mode (port 5432, user `postgres.<project-ref>`) is the one for persistent backends. Render connecting over IPv4 through it is fine.
- Transaction mode (port 6543) does not support prepared statements. This app must not use it.
- Supabase's table lists the direct connection for migrations. Not needed with the IPv4 pooler: whether Render can make outbound IPv6 connections. Unverified: whether Alembic works through the session pooler.
Supabase Data API
- The public schema is exposed through a generated REST API. On existing projects, new tables there get grants for anon, authenticated and service_role by default. RLS is on by default only for tables created in the Dashboard Table Editor; Alembic-created tables do not get it.
- Supabase states the REST endpoints do not respond when the Data API is disabled, whatever the grants or RLS say. Unverified: whether disabling it affects the Storage API; whether the role our app connects with bypasses RLS (do not enable RLS before testing this).
Supabase free plan
- 500 MB database, 1 GB file storage, 50 MB max upload. Projects pause after one week of inactivity and need a manual unpause. Paid plans never pause. Unverified: what counts as activity.
Render health checks
- Check fails after a 5-second timeout. For a running service: after 15 consecutive seconds of failures Render stops routing traffic; after 60 seconds it restarts the service. During a deploy a new instance that fails for 15 minutes cancels the deploy.
Render memory
- Kernel OOM kill when the instance exceeds its limit; Free and Starter are 512 MB, Standard 2 GB. Measured under WSL: 511-513 MB PSS after 8 scorings with Supabase storage. Unknown on Render.

## Steps (one commit per step, tests first where code changes)
0. Inspect, change nothing: where DATABASE_URL, the pool settings (DB_POOL_*) and SSL options are read; what render.yaml declares for the database and for healthCheckPath.
1. Fetch Supabase's current docs on connecting (session pooler string format, required sslmode) and on disabling the Data API. Report the exact steps and whether disabling it affects the Storage API; if the docs don't say, say so.
2. Config: DATABASE_URL points at the session pooler (port 5432). SSL mode and a small pool (DB_POOL_SIZE) are settings read from config, with pool_pre_ping enabled. Production refuses a transaction-mode URL (port 6543) with a clear error and a test.
3. render.yaml: remove the Render Postgres database and the fromDatabase reference; DATABASE_URL becomes a sync: false secret. Update .env.example and docs/deploy_phase3.md.
4. Add an optional integration test that runs only when TEST_SUPABASE_DATABASE_URL is set (skipped otherwise): `alembic upgrade head` through the session pooler, one repository round trip, then `alembic downgrade base`. The user runs it against a throwaway Supabase project.
5. Data API exposure: document the dashboard step to disable the Data API. Ask before adding a migration that revokes privileges on our tables from anon and authenticated (defence in depth). Do NOT enable RLS without first testing that the role our app connects with is not locked out; report what you find.
6. Update docs/stack.md.
7. Render health check: show the healthCheckPath in render.yaml and what that endpoint does. It must point at a liveness endpoint that makes no database or storage call (a Supabase pause or blip must not trigger Render's 60-second restart). /health/ready and /health/services stay out of Render's path. Test: the liveness endpoint returns 200 with the database and storage both failing. Note in docs/deploy_phase3.md that a value set in the Render dashboard can shadow the blueprint.
8. Cache the /health/ready storage reachability result for a short time (a setting, default 30 s, measured with time.monotonic) so repeated probes don't call Supabase each time. Test with a fake clock.
9. Start Docker and run the full suite on Postgres 16 (the last Postgres run failed because Docker was down). Report counts. No merge until this passes.

## Already decided
- A storage outage is reported in /health/ready but does not make it return 503.
- Memory: measure on Render's first deploy; fallback is the Standard instance (2 GB); the structural fix is the lighter embedding runtime from the Phase 4b audit.

## The user's part
Create a throwaway Supabase project with a private bucket; put credentials only in the local gitignored .env; disable the Data API after the exact steps are reported; run the storage smoke test and the database integration test; send the output.