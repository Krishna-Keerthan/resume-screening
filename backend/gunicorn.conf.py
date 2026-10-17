"""
gunicorn.conf.py - the one gunicorn configuration for Docker, Render and the Procfile.

Every launcher runs `gunicorn -c gunicorn.conf.py wsgi:app` from backend/ and repeats
none of these values; they come from config/settings.py (environment variables).

Timeout chain, innermost first: one Groq call (GROQ_CALL_BUDGET_SECONDS, 100 s)
< axios (110 s, frontend/lib/api/client.ts) < gunicorn (GUNICORN_TIMEOUT_SECONDS, 115 s)
< Vercel's proxy (120 s).
"""
import os

from config import get_config

_config = get_config()

# Must be set before torch is imported. With preload_app the app, and so torch and the
# embedding model, is imported right after this file is read, in the master process.
# An OpenMP pool with more than one thread created before the fork can deadlock in the
# workers, and extra threads add nothing to the encoding of a short résumé.
os.environ.setdefault("OMP_NUM_THREADS", str(_config.TORCH_NUM_THREADS))

bind = f"{_config.HOST}:{_config.PORT}"
workers = _config.WORKERS
timeout = _config.GUNICORN_TIMEOUT_SECONDS
loglevel = _config.LOG_LEVEL.lower()

# Load the app (and the embedding model) once in the master; the workers are forked
# from it and share those pages instead of each loading a copy.
preload_app = True
