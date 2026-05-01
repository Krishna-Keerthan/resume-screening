
"""
run.py  —  Development server entry point.

Production uses gunicorn via Procfile / render.yaml.
This file is only for local `python run.py` runs.

Usage:
    python run.py
    APP_ENV=development python run.py
"""

import os

from app import create_app

app = create_app(os.getenv("APP_ENV", "development"))

if __name__ == "__main__":
    app.run(
        host=app.config.get("HOST", "0.0.0.0"),
        port=app.config.get("PORT", 5000),
        debug=app.config.get("DEBUG", False),
        use_reloader=app.config.get("DEBUG", False),
    )