"""
app/api/__init__.py

API package — exports the versioned blueprint for registration in create_app().

Usage (in app/__init__.py):
    from app.api.v1 import api_v1_bp
    app.register_blueprint(api_v1_bp, url_prefix="/api/v1")
"""

from app.api.v1 import api_v1_bp  # noqa: F401

__all__ = ["api_v1_bp"]