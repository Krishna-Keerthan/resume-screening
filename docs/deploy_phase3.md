# Phase 3: deploy wiring (Vercel + Render)

How the pieces are connected, what you must configure by hand, and what to test
after the first deploy. Read this at the start of every Phase 3 session.

## How requests flow

```
browser --https--> Vercel (app domain) --rewrite /api/v1/*--> Render (Flask)
```

- The browser only ever talks to the Vercel domain. `frontend/next.config.js`
  rewrites `/api/v1/*` to `API_PROXY_TARGET` (the Render origin, **no** `/api/v1`).
- The refresh cookie is therefore first-party: host-only (no `Domain`), `Path=/`,
  `HttpOnly`, `SameSite=Lax`, `Secure` in production. `Path=/` is deliberate: the
  Next.js middleware reads the cookie on page requests, not only on `/api` calls.
- CORS is not involved for the browser (same origin). `ALLOWED_ORIGINS` stays set
  to the Vercel origin for tools that call the API directly; there is no wildcard.
- `client.ts` uses the relative base path `/api/v1` and a 110 s timeout, below the
  120 s limit of Vercel's proxy, so a slow call fails with our own error.

## Configure by hand

### Vercel (project settings -> Environment Variables)
| Variable | Value |
|---|---|
| `API_PROXY_TARGET` | `https://<your-service>.onrender.com` (no trailing slash, no `/api/v1`) |

- It is read at **build** time (rewrites are fixed then). Changing it needs a redeploy.
- A production build fails with a clear message if it is unset or ends in `/api/v1`.
- Remove `NEXT_PUBLIC_API_URL` and `INTERNAL_API_URL` if you set them earlier.

### Render (service -> Environment)
| Variable | Value |
|---|---|
| `ALLOWED_ORIGINS` | `https://<your-project>.vercel.app` (add a custom domain here too) |
| `TRUSTED_PROXY_HOPS` | `2` (set in `render.yaml`; verify as described below) |
| `LOG_PROXY_CHAIN` | `true` for the first deploy only (set in `render.yaml`) |
| `REFRESH_COOKIE_SECURE` | nothing to set: defaults to `true` in production |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_BUCKET` | from your Supabase project (`sync: false`: Render asks for them). `STORAGE_PROVIDER=supabase` is set in `render.yaml`. If any of the three is empty the app refuses to start, so a bad deploy fails loudly instead of writing résumés to Render's disk, which is wiped on every deploy. |

Always use the Vercel domain. Logging in on the `*.onrender.com` address directly
would store the cookie on a different host.

## Verify the proxy hop count after the first deploy (do this once)

`TRUSTED_PROXY_HOPS=2` is an estimate (Vercel, then Render's proxy). It has not
been verified against the real deployment. A wrong value does damage either way:

- too low: every user is keyed to a proxy's address and they share one rate-limit bucket;
- too high: a caller can put a forged entry in `X-Forwarded-For` and choose their own bucket.

How to check:

1. Deploy with `LOG_PROXY_CHAIN=true`.
2. Find your own public IP (any "what is my IP" page).
3. On the Vercel site, try to log in (a wrong password is fine).
4. In the Render logs find the warning `TEMPORARY proxy chain check`. It has three fields:
   `forwarded_for` (the raw header), `trusted_hops`, `client_ip` (what the app derived).
5. `client_ip` must equal your public IP.
   - It shows a Vercel or Render address: the count is too low. Raise `TRUSTED_PROXY_HOPS`.
   - It shows an address that is not yours but is the leftmost entry or something
     you can change: the count is too high. Lower it.
   - Count the entries in `forwarded_for`: with the right setting your IP is that
     many places from the right.
6. Repeat with a forged header to be sure:
   `curl -X POST -H "X-Forwarded-For: 1.2.3.4" https://<vercel-app>/api/v1/auth/login ...`.
   The derived `client_ip` must still be your real IP, not `1.2.3.4`.
7. Set the right value, set `LOG_PROXY_CHAIN=false` (or delete it from `render.yaml`).
8. Remove the temporary code in its own commit: `backend/app/core/proxy_chain_log.py`,
   its registration in `app/__init__.py`, the `LOG_PROXY_CHAIN` setting in
   `config/settings.py`, `.env.example` and `render.yaml`, and
   `tests/integration/test_proxy_chain_log.py`.

The log records addresses only, never cookies or tokens.

## Known residual (accepted for now)

Someone who calls the `*.onrender.com` address directly bypasses Vercel. With two
trusted hops they can put their own entry in `X-Forwarded-For` and so choose their
own rate-limit key. The per-email login backstop (`RATE_LIMIT_LOGIN_EMAIL`) still
limits the damage to a single account. The fix is a shared-secret header that
Vercel adds and the backend checks; it is a Phase 6 item in `Repair_Playbook.md`.

## Routes that may hit proxy limits (test by hand)

Vercel's proxy times out at 120 s ([changelog](https://vercel.com/changelog/cdn-origin-timeout-increased-to-two-minutes));
the backend may keep sending data after that, but a single quiet gap over 120 s fails.
I found no documented request-body size limit for external rewrites, so test uploads
rather than assume. Render's free tier can need 30 to 60 s to wake from idle.

| Route | Risk | Test |
|---|---|---|
| `POST /resumes/` (upload, up to `MAX_UPLOAD_MB`, 10 MB) | body size through the proxy; parsing time | upload a ~9 MB PDF and DOCX: expect 201. Upload ~10.5 MB: expect Flask's 413, not a proxy error page |
| Scoring and ranking: `/scores/*`, `GET /jobs/<id>/candidates`, resume score preview | first call loads the embedding model (cold start); many résumés | right after the service wakes, request a score and a ranking; both must return within 110 s |
| Groq routes: job enhance, résumé ai-summary, generate-summary, rewrite-suggestions, analyze, match, and `POST /applications/`, `POST /jobs/` | external call plus retries (`GROQ_TIMEOUT_SECONDS` 30 x `GROQ_MAX_RETRIES`) can exceed 110 s | simulate a slow/failed Groq (bad key) and confirm the UI shows our own error, not a bare proxy error |
| Anything on the first request after idle | Render wake-up plus the above | open the app after 15+ minutes idle and log in |

## After the first deploy, check

- Log in, hard-reload a protected page: the session survives.
- DevTools -> Application -> Cookies: `refresh_token` is on the Vercel domain,
  `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`.
- Upload a résumé, redeploy the backend, the file is still downloadable (item 6, not yet done).
- No tokens or cookies in the Render logs.

## Database on Supabase

Postgres is a Supabase project, not a Render database; `render.yaml` declares none.

- **`DATABASE_URL`** is a `sync: false` secret set in the Render dashboard: the *session
  pooler* string from Supabase's Connect dialog,
  `postgresql://postgres.<project-ref>:<password>@<pooler-host>:5432/postgres`. The pooler
  host (`aws-<n>-<region>.pooler.supabase.com`) cannot be derived from the region; copy it.
  Percent-encode reserved characters in the password (`&`, `#`, `?`, space).
- **Port 5432 only.** Port 6543 is transaction mode, which has no prepared statements;
  production refuses to start with it and says so.
- **Why the session pooler:** Supabase says the shared pooler is IPv4-only on every plan,
  and direct connections are IPv6 on the free plan. Render connecting over IPv4 through the
  pooler is fine, so Render's IPv6 support does not matter. Also not
  verified: that `alembic upgrade head` works through the session pooler (session mode
  supports session state, so it should); the optional integration test checks it.
- **SSL:** `DB_SSLMODE` defaults to `require` in production (encrypted, the server is not
  verified). `verify-full` needs the root certificate from Supabase's database settings.
- **Pool:** production defaults to `DB_POOL_SIZE=3`, `DB_MAX_OVERFLOW=2`, with
  `pool_pre_ping` on; one worker.

## Health checks

`render.yaml` sets `healthCheckPath: /api/v1/health`. That endpoint (`liveness()` in
`app/api/v1/health.py`) returns the status and uptime and makes **no** database, storage or
service call; a test makes the database and storage fail and still gets 200. This matters
because Render stops routing traffic to a running service after 15 s of failed checks and
restarts it after 60 s: a Supabase pause or blip must not do that. `/api/v1/health/ready`
(database, services, storage) and `/api/v1/health/services` stay out of Render's path; use
them by hand or from an uptime monitor.

A health check path set in the Render dashboard is not overwritten by the blueprint and can
shadow it. After creating the service, open Settings → Health Check Path and confirm it reads
`/api/v1/health`.

## Database migrations on deploy

The Render start command is `alembic upgrade head && gunicorn ...`: it runs once
per deploy, before the app starts. Production never calls `db.create_all()`
(`CREATE_TABLES_ON_STARTUP` is false there; development and tests keep it).

- **First deploy, empty database:** `upgrade head` runs 0001, 0002, 0003, 0004, creates
  every table and `alembic_version` (at `0004`), then gunicorn starts. Nothing else
  to do. Checked locally against an empty Postgres 16 with `APP_ENV=production` (a local Postgres
  without SSL needs `DB_SSLMODE=disable`, since production defaults to `require`).
- **Later deploys:** nothing to apply means no change; a new migration is applied
  before the new code serves traffic.
- **A migration fails:** gunicorn does not start and Render keeps the previous
  version running. Read the deploy log, fix, redeploy.
- **Do not** run `alembic stamp` on production, and do not scale beyond one
  instance on the first deploy (every instance runs the command and they would
  race creating the tables).
- Alembic builds the production config, so `SECRET_KEY`, `DATABASE_URL` and
  `RATE_LIMIT_STORAGE_URL` (Redis) must exist in the environment.

## How the server is started

Docker, the Procfile and `render.yaml` (root; `rootDir: backend`) all run the same thing from `backend/`:
`gunicorn -c gunicorn.conf.py wsgi:app` (Render and the Procfile run
`alembic upgrade head` first). `gunicorn.conf.py` reads workers, timeout, bind
address and log level from `config/settings.py`, so no launcher repeats them:

| Setting | Env var | Default |
|---|---|---|
| workers | `WORKERS` | 1 in production, 2 in development |
| timeout | `GUNICORN_TIMEOUT_SECONDS` | 115 |
| bind | `HOST`, `PORT` (Render sets `PORT`) | `0.0.0.0:5000` |
| log level | `LOG_LEVEL` | `WARNING` in production |
| torch / OpenMP threads | `TORCH_NUM_THREADS` | 1 |

`preload_app = True`: the app, and the embedding model, load once in the master and
the workers are forked from it. OpenMP and torch are limited to one thread because a
thread pool created before the fork can deadlock in the workers.

Timeouts, innermost first: one Groq call (`GROQ_CALL_BUDGET_SECONDS`, 100 s; startup
refuses a `GROQ_TIMEOUT_SECONDS` / `GROQ_MAX_RETRIES` pair whose worst case reaches
it, 93 s with the defaults) < axios (110 s, `frontend/lib/api/client.ts`) < gunicorn
(115 s) < Vercel's proxy (120 s). A test fails if any of them is reordered.
`POST /applications/` can make two Groq calls in a row (score explanation, then, for
scores below 0.65, an improvement plan), so it runs inside one shared budget of
`GROQ_CALL_BUDGET_SECONDS` (100 s) that starts when the request started (not when the view
starts) and runs on the monotonic clock: each attempt's timeout is capped by the time left,
retries stop when it is spent, and the improvement plan is skipped when less than
`GROQ_OPTIONAL_CALL_MIN_SECONDS` (25 s) is left. A skipped plan looks the same to the
client as a failed one: `improvement_plan` is empty. The other Groq routes make one call
each, bounded at 93 s.
The non-Groq part of that request, measured with the real embedding model on local
Postgres and no Groq key: 353 ms for the first request after boot, a median of 80 ms
(max 109 ms) for the next seven, about 5 ms of authentication and framework overhead
before the view. Groq calls end 100 s after the request started, leaving 15 s of the
115 s for everything else; these numbers are not from Render's slower CPU and database.

## Memory against Render's 512 MB

Measured with real gunicorn on WSL2 (Python 3.11, CPU torch 2.3, SQLite, development
config): boot, then one DOCX upload and 8 real `POST /scores/match` requests with the
semantic model available. PSS counts shared pages once, so it is the figure to compare
with the instance limit; RSS counts shared pages in every process.

| Workers | Preload | After boot (total PSS) | After 8 scoring requests | Per process RSS after requests |
|---|---|---|---|---|
| 2 | no | 733 MB | 751 MB | workers 466 and 454 MB |
| 2 | yes | 460 MB | **538 MB** | master 452, workers 364 and 377 MB |
| 1 | no | 455 MB | 470 MB | worker 467 MB |
| 1 | yes | 454 MB | 500 MB | master 452, worker 377 MB |

- Preload saves about 210 MB with two workers but does not help with one.
- Two workers do **not** fit in 512 MB once warm, with or without preload. One worker
  fits with little room (470 to 500 MB before Postgres drivers and real
  traffic). This was not measured on Render itself.
- **Production therefore runs one worker** (`WORKERS` defaults to 1 there, and
  `render.yaml` does not set it). Raise it only on an instance with more memory.
- The embedding model (~90 MB) is downloaded when the app is built, by one script,
  `python -m scripts.download_model` (`backend/scripts/download_model.py`), which both
  Render's `buildCommand` and the Dockerfile run. Nothing else names the model or the
  cache path. The path is the `EMBEDDING_CACHE_DIR` setting, an absolute path that
  defaults to `backend/.cache/embeddings` (a relative value is relative to `backend/`,
  not to the working directory), and the running app reads the same setting. The script
  refuses a path outside `backend/`, because on Render only the project directory
  (`/opt/render/project`) is carried from the build to the running service. After
  downloading it loads the model again from the cache with `local_files_only=True` and
  encodes one string, so an incomplete cache fails the build rather than the first start.
- The runtime sets `EMBEDDING_OFFLINE=true` (Dockerfile `ENV`, `render.yaml`) so the model
  loads from the local cache only. Without that, `huggingface_hub` still asks huggingface.co
  about each cached file and, with no network, retries each request for about 20 s, so a
  boot took minutes. With it, a container with `--network none` became healthy in 14 s.
- **If the model is missing, the app does not start.** With `EMBEDDING_OFFLINE=true` and
  no loadable model, startup raises an error naming the model, the cache path and
  `python -m scripts.download_model`; a deploy fails loudly instead of scoring without
  its 40 % semantic component. Online (development) the model is fetched on first run and
  `/health/services` reports `semantic_search: false` if that fails.
- Checked by simulating Render: build in one directory with one `HOME`, then run from `/`
  with an empty `HOME`, no network and `EMBEDDING_OFFLINE=true`. The model loaded from the
  same path. The build wrote 15 files (88 MB) under `<project>/.cache/embeddings` and one
  downloader log under `HOME`, which the runtime does not need. **Not verified on
  Render itself:** that the build's files really are in the running service, which is the
  first thing to check if the app refuses to start with the message above.

### Reading real memory on the first deploy

The app logs one INFO line from the logger `app.memory` (visible even at
`LOG_LEVEL=WARNING`) with `stage`, `pid` and `rss_mb`, read from `/proc/self/status`:

| `stage` | When | Process |
|---|---|---|
| `startup` | the app finished loading | the gunicorn master (preload) |
| `worker_start` | right after each fork | the worker |
| `scored` | after every scored résumé x job pair | the worker |

RSS counts pages shared with the master in every process, so the worker's figure is
higher than the memory it adds. Compare the master's plus the worker's growth with the
512 MB limit, and watch Render's own memory graph for the real total.

## Supabase Storage (résumé files)

Résumés are stored in a **private** Supabase Storage bucket. Render's disk is wiped on every
deploy, so `STORAGE_PROVIDER=supabase` is set in `render.yaml`; local disk is for development only.

### Create the bucket

In the Supabase dashboard (Storage; the exact wording of the screens may differ):

1. Create a bucket, for example `resumes`, with **Public bucket turned off**. Private is Supabase's
   default; check it anyway.
2. Optional, but cheap: set the bucket's file size limit to match `MAX_UPLOAD_MB` (10 MB) and the allowed
   types to `application/pdf` and
   `application/vnd.openxmlformats-officedocument.wordprocessingml.document`.
3. **Add no policy** on `storage.objects` for this bucket. A private bucket without a policy cannot be
   read by the `anon` or `authenticated` roles, which is what we want: the only reader is our server,
   using the service-role key (it bypasses row-level security), and the only way a browser gets a file
   is a signed URL from `GET /api/v1/resumes/<id>/download`, after the ownership check.
4. Never switch the bucket to public later. The app never builds a public URL (a test fails if any
   code or response does), but a public bucket would make every object readable by anyone who knows
   its path.

### Where the three values go

Set them in the **Render dashboard** (`render.yaml` lists them with `sync: false`, so Render asks for
them when the blueprint is created). They are not set in Vercel, not in the frontend, not in a commit.

| Variable | Value |
|---|---|
| `SUPABASE_URL` | The project's base URL, `https://<project-ref>.supabase.co`. No path: the app adds `/storage/v1` itself, and refuses to start if you paste a URL with a path. |
| `SUPABASE_BUCKET` | The bucket's name, for example `resumes`. |
| `SUPABASE_SERVICE_ROLE_KEY` | A server-side key from Settings, API Keys. Either a new-style secret key (`sb_secret_...`, preferred) or the legacy `service_role` key (a JWT starting `eyJ`). The app sends a secret key in the `apikey` header only and a JWT in both `apikey` and `Authorization`, as Supabase documents. Supabase plans to deprecate the legacy keys by the end of 2026. |

The service-role key bypasses row-level security, so treat it like a database password: it is never
logged, returned in a response or put in an error message (tests check this for both key kinds), and
Supabase rejects secret keys used from a browser. To rotate it, change the variable in Render and
redeploy; nothing else holds a copy.

### What the app checks, and what it does not

At startup the app refuses to start if any of the three values is empty, or if `SUPABASE_URL` is not an
http(s) URL without a path. It does **not** contact Supabase at startup, so a wrong key, a missing
bucket or a public bucket is **not** caught there. `scripts/supabase_smoke_test.py` catches them: run it
once against the real project before the first user (`docs/supabase-smoke-test.md`). It checks that the
bucket is private, the plain URLs fail, a signed URL works and then expires, and delete removes the
object.

### Behaviour

- Upload: a random key (`<32 hex>.<pdf|docx>`); the user's filename is never sent to Supabase.
- Download: the route returns `{ "url": <signed URL>, "expires_in": 300 }` after the ownership check;
  the URL stops working after `DOWNLOAD_URL_TTL_SECONDS` (300).
- Delete: removes the object; a failed delete is logged and does not block the database soft-delete.
- A file that is missing from the bucket is a 404 `FILE_NOT_FOUND`; any other store failure is a 502
  `STORAGE_UNAVAILABLE` without internals.

## First deploy, step by step

1. **Accounts and secrets:** a Supabase project with a private bucket (its URL, service-role key and
   bucket name; see "Supabase Storage" above); a Groq API key
   (optional, LLM features are off without it).
2. **The blueprint is `render.yaml` in the repository root** (where Render looks by
   default). The web service uses `runtime: python` with `rootDir: backend`, so its
   build and start commands run from `backend/`. There is no Docker field to set:
   Render does not use the Dockerfile for this service. Field names come from
   https://render.com/docs/blueprint-spec. The file was also checked against
   https://render.com/schema/render.yaml.json (see the commit message for how).
3. **Create the Render blueprint** (web service and the `ats-ratelimit` Key Value; the
   database is on Supabase, see "Database on Supabase"). Fill the `sync: false` values:
   `DATABASE_URL`, `SUPABASE_URL`,
   `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_BUCKET`, `GROQ_API_KEY`. Leave
   `ALLOWED_ORIGINS` as a placeholder for now. Keep one instance.
4. **Let the first deploy run.** The log shows `alembic upgrade head` running 0001,
   0002, 0003 and 0004, then gunicorn loading the model and starting. If a Supabase
   value is missing, the app refuses to start and says which one is missing.
5. **Check the backend directly:** `GET https://<service>.onrender.com/api/v1/health`
   returns 200. Do not log in here.
6. **Create the Vercel project** from `frontend/`, set `API_PROXY_TARGET` to the
   Render origin (no `/api/v1`), and deploy. The build fails with a clear message if
   it is unset.
7. **Back on Render,** set `ALLOWED_ORIGINS` to the Vercel URL and redeploy.
8. **Register and log in on the Vercel URL.** Check the cookie in DevTools and hard
   reload a protected page.
9. **Verify the proxy hop count** (section above), then turn `LOG_PROXY_CHAIN` off.
10. **Test the proxy limits** (upload sizes, first request after idle), and run
    `docs/supabase-smoke-test.md` with real credentials. Do this before step 8 if you can: it is the
    only check that the bucket is private and the key works.
