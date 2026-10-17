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
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | from your Cloudinary dashboard (`sync: false`: Render asks for them). `STORAGE_PROVIDER=cloudinary` is set in `render.yaml`. If any of the three is empty the app refuses to start, so a bad deploy fails loudly instead of writing résumés to Render's disk, which is wiped on every deploy. |

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

## Database migrations on deploy

The Render start command is `alembic upgrade head && gunicorn ...`: it runs once
per deploy, before the app starts. Production never calls `db.create_all()`
(`CREATE_TABLES_ON_STARTUP` is false there; development and tests keep it).

- **First deploy, empty database:** `upgrade head` runs 0001, 0002, 0003, creates
  every table and `alembic_version` (at `0003`), then gunicorn starts. Nothing else
  to do. Checked locally against an empty Postgres 16 with `APP_ENV=production`.
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
One call is bounded, but one request is not: `POST /applications/` can make two Groq
calls in a row (score explanation, then the improvement plan), so its worst case is
above 115 s.

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
  fits with little room (470 to 500 MB before Postgres drivers, Cloudinary and real
  traffic). This was not measured on Render itself.
- **Production therefore runs one worker** (`WORKERS` defaults to 1 there, and
  `render.yaml` does not set it). Raise it only on an instance with more memory.
- The embedding model (~90 MB) is downloaded when the app is built, not at cold start:
  Render's `buildCommand` ends with `python -m scripts.download_model`, and the
  Dockerfile runs it in its own layer (the image grew from 2.48 GB to 2.66 GB). The
  runtime then sets `EMBEDDING_OFFLINE=true` (Dockerfile `ENV`, `render.yaml`) so the
  model loads from the local cache only. Without that, `huggingface_hub` still asks
  huggingface.co about each cached file and, with no network, retries each request for
  about 20 s, so a boot took minutes. With it, a container with `--network none`
  became healthy in 14 s and scored a résumé. **Not verified on Render:** that files
  written under `backend/.cache/` by the build command are still there when the
  service starts. If `scored` shows `semantic_available: false`, or the log says the
  model failed to load, that is the first thing to check.

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

## First deploy, step by step

1. **Accounts and secrets:** Cloudinary cloud name, API key and secret; a Groq API key
   (optional, LLM features are off without it).
2. **The blueprint is `render.yaml` in the repository root** (where Render looks by
   default). The web service uses `runtime: python` with `rootDir: backend`, so its
   build and start commands run from `backend/`. There is no Docker field to set:
   Render does not use the Dockerfile for this service. Field names come from
   https://render.com/docs/blueprint-spec. The file was also checked against
   https://render.com/schema/render.yaml.json (see the commit message for how).
3. **Create the Render blueprint** (web service, `ats-postgres`, `ats-ratelimit`
   Key Value). Fill the `sync: false` values: `CLOUDINARY_CLOUD_NAME`,
   `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`, `GROQ_API_KEY`. Leave
   `ALLOWED_ORIGINS` as a placeholder for now. Keep one instance.
4. **Let the first deploy run.** The log shows `alembic upgrade head` running 0001,
   0002 and 0003, then gunicorn loading the model and starting. If the Cloudinary
   values are incomplete, the app refuses to start and says which one is missing.
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
    `docs/cloudinary-smoke-test.md` with real credentials.
