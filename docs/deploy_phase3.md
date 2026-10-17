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
