
"""
wsgi.py  —  Gunicorn / production WSGI entry point.

Gunicorn command (Docker, Render, Procfile):
    gunicorn -c gunicorn.conf.py wsgi:app

Workers, timeout, bind address and log level come from gunicorn.conf.py. With its
preload_app = True this module is imported once, in the master process, and the
workers are forked from it.
"""

import os

from app import create_app

app = create_app(os.getenv("APP_ENV", "development"))