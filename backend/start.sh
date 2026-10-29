#!/bin/sh
# The one start command for the Dockerfile (Render and docker compose's image) and the Procfile.
# gunicorn's settings live in gunicorn.conf.py, which reads config/settings.py.
set -e
alembic upgrade head
exec gunicorn -c gunicorn.conf.py wsgi:app
