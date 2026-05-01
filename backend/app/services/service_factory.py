"""
app/services/service_factory.py

Service factory — builds and caches all service instances.

Changes vs previous version:
  - StorageService is instantiated here and stored on the Services dataclass.
  - Routes that need storage access can call:
        svcs = current_app.extensions["services"]
        svcs.storage.upload(...)
    OR instantiate StorageService.from_config() directly (both are fine —
    StorageService is lightweight, not a singleton).
  - Everything else is identical to the previous version.
"""

import logging
from dataclasses import dataclass
import os

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

logger = logging.getLogger(__name__)


@dataclass
class Services:
    """Container for all service instances."""
    embedding:            object
    groq:                 object
    resume_parser:        object
    job_parser:           object
    keyword_matcher:      object
    semantic_matcher:     object
    experience_scorer:    object
    section_quality:      object
    explainability:       object
    ats_scorer:           object
    resume_analysis:      object
    smart_job_posting:    object
    job_recommendations:  object
    candidate_ranking:    object
    recruiter_analytics:  object
    storage:              object   # StorageService backend instance


class ServiceFactory:
    """
    Builds all services with their dependencies in dependency order:
      infrastructure → scoring components → orchestrators → high-level
    """

    @staticmethod
    def create_all(config, db_session=None) -> Services:
        """
        Build all services from a config object.

        Args:
            config:     Flask config dict or config class.
            db_session: SQLAlchemy session (optional — used in tests).

        Returns:
            Services dataclass with all service instances.
        """
        from app.services.embedding_service import EmbeddingService
        from app.services.groq_service import GroqService
        from app.services.resume_parser import ResumeParserService
        from app.services.job_parser import JobParserService
        from app.services.keyword_matcher import KeywordMatcherService
        from app.services.semantic_matcher import SemanticMatcherService
        from app.services.experience_scorer import ExperienceScorerService
        from app.services.section_quality_scorer import SectionQualityScorerService
        from app.services.explainability_engine import ExplainabilityEngine
        from app.services.ats_scorer import AtsScorerService
        from app.services.resume_analysis_service import ResumeAnalysisService
        from app.services.smart_job_posting_service import SmartJobPostingService
        from app.services.job_recommendation_service import JobRecommendationService
        from app.services.candidate_ranking_service import CandidateRankingService
        from app.services.recruiter_analytics_service import RecruiterAnalyticsService
        from app.services.storage_service import StorageService

        def cfg(key, default=None):
            if isinstance(config, dict):
                return config.get(key, default)
            return getattr(config, key, default)

        # ── Infrastructure ─────────────────────────────────────────────────────
        embedding_svc = EmbeddingService.get_instance(
            model_name=cfg("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
            cache_dir=cfg("EMBEDDING_CACHE_DIR", ".cache/embeddings"),
        )
        embedding_svc._cache._capacity = cfg("EMBEDDING_CACHE_SIZE", 512)
        embedding_svc._ensure_loaded()

        groq_svc = GroqService(
            api_key=cfg("GROQ_API_KEY", ""),
            model=cfg("GROQ_MODEL", "llama-3.1-8b-instant"),
            max_tokens=cfg("GROQ_MAX_TOKENS", 1024),
            temperature=cfg("GROQ_TEMPERATURE", 0.3),
            timeout=cfg("GROQ_TIMEOUT_SECONDS", 30),
        )

        # ── Storage backend ────────────────────────────────────────────────────
        # Lightweight — not a singleton. Routes can also call
        # StorageService.from_config(current_app.config) directly.
        storage_svc = StorageService.from_config(config)
        logger.info(
            "Storage backend initialised",
            extra={"provider": storage_svc.provider},
        )

        # ── Parsing ────────────────────────────────────────────────────────────
        resume_parser = ResumeParserService()
        job_parser    = JobParserService()

        # ── Scoring components ─────────────────────────────────────────────────
        keyword_matcher = KeywordMatcherService()

        semantic_matcher = SemanticMatcherService(
            embedding_service=embedding_svc,
        )

        experience_scorer     = ExperienceScorerService()
        section_quality_scorer = SectionQualityScorerService()

        # ── Explainability ─────────────────────────────────────────────────────
        explainability_engine = ExplainabilityEngine(
            groq_service=groq_svc,
            keyword_matcher=keyword_matcher,
        )

        # ── Repositories ───────────────────────────────────────────────────────
        repos = _build_repos(db_session)

        # ── Orchestrators ──────────────────────────────────────────────────────
        ats_scorer = AtsScorerService(
            keyword_matcher=keyword_matcher,
            semantic_matcher=semantic_matcher,
            experience_scorer=experience_scorer,
            section_quality_scorer=section_quality_scorer,
            explainability_engine=explainability_engine,
            ats_score_repo=repos["ats_score"],
            weights=cfg("ATS_SCORE_WEIGHTS", None),
            parallel_scoring=cfg("ATS_PARALLEL_SCORING", True),
            scoring_timeout_seconds=cfg("ATS_SCORING_TIMEOUT", 10.0),
            threshold_excellent=cfg("ATS_SCORE_THRESHOLD_EXCELLENT", 0.80),
            threshold_good=cfg("ATS_SCORE_THRESHOLD_GOOD",      0.65),
            threshold_fair=cfg("ATS_SCORE_THRESHOLD_FAIR",      0.50),
        )

        resume_analysis_svc = ResumeAnalysisService(
            parser=resume_parser,
            section_quality_scorer=section_quality_scorer,
            groq_service=groq_svc,
            resume_repo=repos["resume"],
        )

        smart_job_svc = SmartJobPostingService(
            job_parser=job_parser,
            groq_service=groq_svc,
            job_repo=repos["job"],
        )

        job_rec_svc = JobRecommendationService(
            ats_scorer=ats_scorer,
            ats_score_repo=repos["ats_score"],
            job_repo=repos["job"],
            top_n=cfg("TOP_N_JOB_RECOMMENDATIONS", 10),
        )

        candidate_rank_svc = CandidateRankingService(
            application_repo=repos["application"],
            ats_score_repo=repos["ats_score"],
            candidate_repo=repos["candidate"],
        )

        recruiter_analytics_svc = RecruiterAnalyticsService(
            job_repo=repos["job"],
            application_repo=repos["application"],
            ats_score_repo=repos["ats_score"],
        )

        logger.info(
            "Services initialised",
            extra={
                "groq_available":      groq_svc.available,
                "embedding_available": semantic_matcher.available,
                "storage_provider":    storage_svc.provider,
            },
        )

        return Services(
            embedding=embedding_svc,
            groq=groq_svc,
            resume_parser=resume_parser,
            job_parser=job_parser,
            keyword_matcher=keyword_matcher,
            semantic_matcher=semantic_matcher,
            experience_scorer=experience_scorer,
            section_quality=section_quality_scorer,
            explainability=explainability_engine,
            ats_scorer=ats_scorer,
            resume_analysis=resume_analysis_svc,
            smart_job_posting=smart_job_svc,
            job_recommendations=job_rec_svc,
            candidate_ranking=candidate_rank_svc,
            recruiter_analytics=recruiter_analytics_svc,
            storage=storage_svc,
        )


def _build_repos(db_session=None) -> dict:
    """
    Build repository instances.

    Falls back to MagicMock repos in unit test environments where
    ORM models are not available.
    """
    try:
        from app.repositories import (
            CandidateRepository,
            RecruiterRepository,
            JobRepository,
            ResumeRepository,
            ApplicationRepository,
            AtsScoreRepository,
        )
        kwargs = {"session": db_session} if db_session else {}
        return {
            "candidate":   CandidateRepository(**kwargs),
            "recruiter":   RecruiterRepository(**kwargs),
            "job":         JobRepository(**kwargs),
            "resume":      ResumeRepository(**kwargs),
            "application": ApplicationRepository(**kwargs),
            "ats_score":   AtsScoreRepository(**kwargs),
        }
    except Exception as exc:
        logger.warning(
            "Could not import repositories (%s) — using mock repos.", exc
        )
        from unittest.mock import MagicMock
        return {k: MagicMock() for k in
                ("candidate", "recruiter", "job", "resume", "application", "ats_score")}