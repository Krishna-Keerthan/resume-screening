"""
app/repositories

Repository pattern — data access layer between the service layer and SQLAlchemy.

Why a repository layer?
  - Services never write SQL/ORM queries directly.
  - All DB queries are isolated here — testable, swappable, cacheable.
  - When we add Redis caching or switch from SQLite to PostgreSQL, only
    repository methods change — services and routes are untouched.

Pattern:
  - BaseRepository[T]: Generic CRUD operations for any model.
  - Concrete repos (CandidateRepository, JobRepository, etc.) extend it
    with domain-specific query methods.
  - All repository methods operate within the Flask request context
    (db.session is request-scoped via Flask-SQLAlchemy).

Usage:
    from app.repositories import CandidateRepository
    repo = CandidateRepository()
    candidate = repo.get_by_id("abc-123")
    candidates, total = repo.list_active(page=1, limit=20)
"""

from app.repositories.base        import BaseRepository
from app.repositories.candidate   import CandidateRepository
from app.repositories.recruiter   import RecruiterRepository
from app.repositories.job         import JobRepository
from app.repositories.resume      import ResumeRepository
from app.repositories.application import ApplicationRepository
from app.repositories.ats_score   import AtsScoreRepository

__all__ = [
    "BaseRepository",
    "CandidateRepository",
    "RecruiterRepository",
    "JobRepository",
    "ResumeRepository",
    "ApplicationRepository",
    "AtsScoreRepository",
]