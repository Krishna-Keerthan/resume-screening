
"""
wsgi.py  —  Gunicorn / production WSGI entry point.

Gunicorn command (Render):
    gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120

The app object is resolved here once and reused by all gunicorn workers.
"""

import os

from app import create_app

app = create_app(os.getenv("APP_ENV", "development"))