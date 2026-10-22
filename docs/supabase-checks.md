# Supabase checks (manual, need a real throwaway project)

**Status: written, not run against a real project.** The automated tests run the backend and the
storage script against a fake Supabase server (`backend/tests/unit/fake_supabase.py`). They prove which
HTTP calls we make and that the script fails when a bucket is public or a signed URL never expires. They
do not prove that Supabase answers the way the fake does. Run both checks once per environment and record
the result in the log at the end.

There are two checks, and they need different variables:

| Check | What it proves | Command | Variables |
|---|---|---|---|
| Storage smoke test | private bucket, signed URLs, expiry, delete | `python ../scripts/supabase_smoke_test.py` | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_BUCKET` |
| Database integration test | SSL, Alembic through the session pooler, migration 0005, one repository round trip | `pytest -q tests/integration/test_supabase_database.py` | `TEST_SUPABASE_DATABASE_URL` (optional: `DB_SSLMODE`) |

Order, per the settled decision in `docs/STATUS.md`: run both on the **throwaway** project, disable the
Data API (`docs/deploy_phase3.md`, "Data API exposure"), run both again, and only then repeat on the real
project. Never use real résumés or a project that holds other tables.

## Setup (once)

1. Create a throwaway Supabase project. Create a **private** bucket (the "Public bucket" switch off) named
   `resumes-smoke-test` with **no policies**.
2. Put the credentials in `backend/.env` (gitignored; `git check-ignore backend/.env` must print the path):

   ```
   SUPABASE_URL=https://<project>.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=<Project Settings -> API; server-side only>
   SUPABASE_BUCKET=resumes-smoke-test
   TEST_SUPABASE_DATABASE_URL=postgresql://postgres.<ref>:<password>@<pooler-host>:5432/postgres
   ```

   The database URL is the **session pooler** string from the Connect dialog, port **5432** (not 6543).
   Percent-encode `&`, `#`, `?` and spaces in the password.
3. The database must be **empty**: the test refuses to run (before it changes anything) if `public` has any
   table other than `alembic_version`, and it ends with `alembic downgrade base`, which drops every table the
   app owns.
4. Optional `DB_SSLMODE` in the same file. Leave it out for Supabase: the production default, `require`, is
   what the test checks. Set `disable` only for a local Postgres without SSL (see "Rehearsing against a local
   Postgres").

The database test needs nothing else: `SECRET_KEY` and the Redis URL (`RATE_LIMIT_STORAGE_URL`), which the
production config insists on, are made-up placeholders set by the test. The Redis host is under `.invalid`,
which cannot resolve, and a test checks that Python never looked it up. No Redis has to run.

## Commands (WSL, from PowerShell)

`scripts/run_supabase_check.sh` reads `backend/.env` line by line (it does not source it, so `&`, `$` or backticks in a value are taken literally) into its own process environment without printing it (it strips
Windows line endings, which would otherwise end up inside the values), then runs one check from `backend/`.
Call it as a script file: quoting a long command through `wsl bash -c` from PowerShell or Git Bash mangles
`$`, quotes and backslashes (a first attempt at an inline command silently ran with garbage values).

```powershell
wsl bash /mnt/d/VS_CODE/resume_screening/scripts/run_supabase_check.sh storage
wsl bash /mnt/d/VS_CODE/resume_screening/scripts/run_supabase_check.sh database
```

Storage prints one `PASS` / `FAIL` line per step, then `done`, and exits non-zero at the first failure. It
never prints the key, an object key or a signed URL. The object it uploads is deleted whatever happens. It
takes about 15 s (it waits for a 5 s signed URL to expire, plus 5 s grace).

Database prints the pytest summary; you want `10 passed` and no skips.

Before running either check, the script verifies its variables (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
`SUPABASE_BUCKET` for storage; `TEST_SUPABASE_DATABASE_URL` for database). If any is missing or empty it
prints `missing or empty in the environment and in <file>: NAME ...` (names only, never values) and exits **3**
without running anything, so a missing variable can no longer look like a skipped, successful test run.
Exit 2 is a bad argument or no env file.

**Do not run `pytest tests/integration/test_supabase_database.py` directly as the check.** Importing the app
loads `backend/.env` through `python-dotenv`, so a plain `pytest` also picks up `TEST_SUPABASE_DATABASE_URL`
from that file and will run against it; without the variable it reports 7 skipped. Use the script, which
names what is missing.

Send back only the `PASS`/`FAIL` lines and the pytest summary line. The scripts never print the URL or
password, but a pytest traceback can echo a driver error: if one shows a connection string, do not paste it.
Afterwards run `git status --short`: nothing should be untracked or modified.

## Storage smoke test: what each step means

| Step | Checks | If it fails |
|---|---|---|
| 1 | the bucket exists and `public` is `false` (read with the service-role key) | The script prints the same line for **every** cause: the bucket is public, it does not exist (wrong `SUPABASE_BUCKET`), the key is wrong or the wrong kind (401/403), or `SUPABASE_URL` is wrong. Check the bucket name and its "Public bucket" switch first, then the key. |
| 2 | an upload is accepted and the key is `<32 hex>.pdf` | The backend generates the key, so a failure here means the key format changed in code. An upload Supabase rejects raises `StorageError` and the script stops with a traceback instead of a `FAIL` line. |
| 3 | `.../object/public/<bucket>/<key>` and an unauthenticated read of `.../object/<bucket>/<key>` both fail | The object is readable without a credential. Stop: the bucket is effectively public or has a policy. Remove the policy and re-check the switch. |
| 4 | a signed URL returns the original bytes with no credentials | The signed-URL response differs from what the backend reads (`signedURL`, a path starting `/object/sign/`, prefixed with `<SUPABASE_URL>/storage/v1`), or the object did not upload intact. |
| 5 | the signed URL stops working after its 5 s lifetime plus 5 s grace | The URL does not expire. Do not ship: download links would live forever. |
| 6 | after `delete()` there is no signed URL and no download (`StorageNotFound` for both) | Delete did not remove the object, or Supabase reports a missing object differently. The backend treats HTTP 404, and HTTP 400 with `statusCode` `"404"`, as not found. |

On a 401: the backend always sends `apikey: <key>`, and also `Authorization: Bearer <key>` only when the
key is a JWT (the legacy `service_role` key, which starts with `eyJ`). New-style secret keys
(`sb_secret_...`) are not JWTs and belong in `apikey` only. If one kind is rejected, try the other.

## Database integration test: what each test means

The 7 tests that touch the database are skipped without `TEST_SUPABASE_DATABASE_URL`; the 3 guard tests
(a SQLite stand-in for the empty-database check) always run, which is why `10 passed` is the full result.

| Test | Checks | If it fails |
|---|---|---|
| fixtures (the database tests error) | the placeholders and URL build a `ProductionConfig`, the app's engine can start, and the database has no table besides `alembic_version` | `the database already has N table(s) besides alembic_version`: use an empty project. A connection error: wrong host, password or port; the direct `db.<ref>.supabase.co` host is IPv6-only on the free plan, so use the pooler host. An `EnvironmentError` about the URL: port 6543, or a missing `DATABASE_URL`. |
| `test_the_guard_*` (3) | the refusal logic, on SQLite | The guard no longer refuses a database with tables: stop, the downgrade could drop someone else's data. |
| `test_the_production_defaults_reach_the_apps_engine` | `DB_SSLMODE` is `require` (or what the environment sets), pool size 3 and overflow 2, on the config and on the live engine's pool | A default changed, or `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` no longer reach the engine options. |
| `test_port_6543_is_refused_by_the_app_config_and_by_alembic` | the transaction-mode port is rejected by the app config and by Alembic's own connection, before any connection is made | Port 6543 was accepted somewhere: prepared statements would break. |
| `test_the_app_connects_with_the_configured_ssl_mode` | the app's engine is on SSL, unless `DB_SSLMODE=disable` | The connection is unencrypted although `require` was configured. |
| `test_db_sslmode_reaches_alembics_own_connection` | with `verify-full` and a missing root certificate, Alembic fails on the certificate (with `DB_SSLMODE=disable` set, on a server without SSL: on "does not support SSL") | `DB_SSLMODE` does not reach `migrations/env.py`, so migrations would run with a different SSL mode than the app. |
| `test_migrations_run_through_the_session_pooler_and_a_repository_round_trips` | `alembic upgrade head` works through the pooler; `anon` and `authenticated` hold zero grants in `public` (migration 0005); a candidate can be saved, read and deleted | A non-zero return code shows the last 600 characters of Alembic's stderr: a pooler or permissions problem. `anon/authenticated still hold N table grants`: migration 0005 did not take effect on this project. A repository error: the schema or connection mode is wrong. |
| `test_downgrade_to_base_removes_the_tables` | `alembic downgrade base` leaves only `alembic_version` | Leftover tables mean the downgrade is incomplete. Drop them by hand before the next run. |
| `test_the_placeholder_redis_host_was_never_looked_up` | no Python-level lookup of the placeholder Redis host happened during the run | Something in the test path initialises the rate limiter. Psycopg resolves the database host inside libpq, so this test cannot see database lookups, and the Alembic subprocesses are covered only by the host not resolving. |

### Rehearsing against a local Postgres

Proves the setup works without a Supabase project; it is **not** a Supabase result. On a local Postgres 16
without SSL, in a scratch database (the test creates and drops the app's tables in it):

```
TEST_SUPABASE_DATABASE_URL=postgresql://postgres:<password>@localhost:<port>/<scratch-db>
DB_SSLMODE=disable
```

Differences from Supabase: `anon` and `authenticated` do not exist, so the grant counts are 0 trivially;
pooler behaviour is not exercised; the SSL tests check the `disable` path.

After the Data API is disabled, run **both** checks again. Disabling it is not documented to affect either;
this run is what tells you. If a check fails only after disabling it, turn the Data API back on and report
which step failed.

## Also check by hand once

- `GET /api/v1/resumes/<id>/download` as the owning candidate returns `{ "url": ..., "expires_in": 300 }`,
  and the URL downloads the file.
- The same call as another candidate returns 403, and as a recruiter without an application returns 403.
- In the Supabase dashboard (Storage), the bucket shows as private and has no policies.

## Result log

| Date | Environment | Who | Data API | Storage steps 1-6 | Database test | Notes |
|------|-------------|-----|----------|-------------------|---------------|-------|
|      |             |     | on       | not run           | not run       |       |
|      |             |     | off      | not run           | not run       |       |
