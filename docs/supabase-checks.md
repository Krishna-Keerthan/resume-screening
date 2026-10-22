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
| Database integration test | SSL, Alembic through the session pooler, migration 0005, one repository round trip | `scripts/run_supabase_check.sh database` | `TEST_SUPABASE_DATABASE_URL`, `CONFIRM_SUPABASE_REF` (the script sets `RUN_SUPABASE_TESTS=1` itself; optional: `DB_SSLMODE`) |

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
   CONFIRM_SUPABASE_REF=<ref>
   ```

   The database URL is the **session pooler** string from the Connect dialog, port **5432** (not 6543).
   Percent-encode `&`, `#`, `?` and spaces in the password. `<ref>` is the project reference: the part of
   the user name after `postgres.`. `CONFIRM_SUPABASE_REF` must repeat it. That is deliberate: the test
   drops tables, so it will not touch a Supabase project you have not named a second time.
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

Database first prints `Supabase project ref: <ref>` (the ref only, never the URL, so you can see which
project is targeted), then the pytest summary; you want `21 passed` and no skips.

Before running either check, the script verifies its variables (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
`SUPABASE_BUCKET` for storage; `TEST_SUPABASE_DATABASE_URL` for database, plus `CONFIRM_SUPABASE_REF` when that
URL contains `supabase`). If any is missing or empty it
prints `missing or empty in the environment and in <file>: NAME ...` (names only, never values) and exits **3**
without running anything, so a missing variable can no longer look like a skipped, successful test run.
Exit 2 is a bad argument or no env file.

**A plain `pytest` never runs the database tests.** They need `TEST_SUPABASE_DATABASE_URL` *and*
`RUN_SUPABASE_TESTS=1`; only the script sets the flag, so exporting the URL in a shell is not enough (7
skipped, with the reason naming both variables). The test session also never reads `backend/.env`:
`tests/conftest.py` replaces `dotenv.load_dotenv` before the app is imported, because `config/settings.py`
would otherwise fill the environment from that file on import. The script reads the file itself.

If the URL points at Supabase, the test refuses to start (nothing is changed) unless `CONFIRM_SUPABASE_REF`
equals the ref in the URL's user name, and a URL whose user name has no ref (the direct `db.<ref>` host) is
refused: use the session-pooler URL. Both messages name the ref and variable, never the URL.

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

The 7 tests that touch the database are skipped without the URL and `RUN_SUPABASE_TESTS=1`. The other 14
always run, with no database: the 3 empty-database guard tests (on SQLite), the gate (including two
subprocess runs of this file that prove a plain pytest skips even with the URL set), and the ref and
confirmation checks. `21 passed` is the full result of the script.

| Test | Checks | If it fails |
|---|---|---|
| fixtures (the database tests error) | the placeholders and URL build a `ProductionConfig`, the app's engine can start, and the database has no table besides `alembic_version` | `the database already has N table(s) besides alembic_version`: use an empty project. A connection error: wrong host, password or port; the direct `db.<ref>.supabase.co` host is IPv6-only on the free plan, so use the pooler host. An `EnvironmentError` about the URL: port 6543, or a missing `DATABASE_URL`. |
| `test_the_project_ref_*`, `test_a_supabase_*`, `test_the_matching_ref_*`, `test_the_tests_need_*`, `test_gate_subprocess_*` | the ref is read from the pooler user name; a Supabase target needs the matching `CONFIRM_SUPABASE_REF` and the messages hide the URL; both variables are needed to run | These are the safeguards against changing the wrong database: do not run the database tests until they pass. |
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

To rehearse the ref printing and confirmation too, give the URL a Supabase-looking host and point libpq
at the local server with `hostaddr` (no DNS lookup happens): create a role named `postgres.rehearsal`, then
use `postgresql://postgres.rehearsal:<password>@local.supabase.test:<port>/<scratch-db>?hostaddr=127.0.0.1`
and `CONFIRM_SUPABASE_REF=rehearsal`.

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
