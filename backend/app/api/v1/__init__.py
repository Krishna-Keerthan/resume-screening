"""
app/api/v1/__init__.py

Version 1 API — blueprint registration.

All v1 routes are mounted under /api/v1 in create_app().

Resource layout:
  /auth         — JWT login, register, refresh, logout  ← NEW
  /health       — liveness + readiness probes
  /candidates   — candidate profiles + resume upload
  /recruiters   — recruiter accounts + analytics
  /jobs         — job postings + AI enhancement + candidate ranking
  /resumes      — resume management + AI analysis
  /applications — candidate applications + stage management
  /scores       — ATS scoring, matching, recommendations
  /analytics    — aggregated dashboard metrics
"""

from flask import Blueprint

from .analytics    import analytics_bp
from .applications import applications_bp
from .auth         import auth_bp           # ← NEW
from .candidates   import candidates_bp
from .health       import health_bp
from .jobs         import jobs_bp
from .recruiters   import recruiters_bp
from .resumes      import resumes_bp
from .scoring      import scoring_bp

# Master v1 blueprint — all resource blueprints are registered onto this
api_v1_bp = Blueprint("api_v1", __name__)

api_v1_bp.register_blueprint(auth_bp,         url_prefix="/auth")          # /auth  ← NEW
api_v1_bp.register_blueprint(health_bp)                                     # /health
api_v1_bp.register_blueprint(candidates_bp,   url_prefix="/candidates")    # /candidates
api_v1_bp.register_blueprint(recruiters_bp,   url_prefix="/recruiters")    # /recruiters
api_v1_bp.register_blueprint(jobs_bp,         url_prefix="/jobs")          # /jobs
api_v1_bp.register_blueprint(resumes_bp,      url_prefix="/resumes")       # /resumes
api_v1_bp.register_blueprint(applications_bp, url_prefix="/applications")  # /applications
api_v1_bp.register_blueprint(scoring_bp,      url_prefix="/scores")        # /scores
api_v1_bp.register_blueprint(analytics_bp,    url_prefix="/analytics")     # /analytics


__all__ = ["api_v1_bp"]