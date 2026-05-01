"""
app/core/extensions.py

All Flask extension instances are declared here and initialised lazily
via their init_app() pattern in create_app().

This avoids circular imports — models import from core.database, routes import
from core.extensions, but nothing imports from app/__init__.py directly.

Pattern:
    Declare here (no app binding yet).
    Call ext.init_app(app) inside create_app().

Currently registered:
    cors — Flask-CORS for cross-origin requests.
"""

from flask_cors import CORS

# CORS instance — configured in create_app() with allowed origins
cors = CORS()