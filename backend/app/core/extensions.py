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
    cors    — Flask-CORS for cross-origin requests.
    limiter — Flask-Limiter; see app/core/rate_limit.py.
"""

from flask_cors import CORS

from app.core.rate_limit import config_limit, new_limiter, user_or_ip_key

# CORS instance — configured in create_app() with allowed origins
cors = CORS()

limiter = new_limiter()

# One per-user budget (RATE_LIMIT_LLM) shared by every route that can call Groq.
# Put it BELOW @require_auth so anonymous callers get 401, not 429, and the
# key is the authenticated user.
llm_limit = limiter.shared_limit(
    config_limit("RATE_LIMIT_LLM"), scope="llm", key_func=user_or_ip_key, override_defaults=False,
)