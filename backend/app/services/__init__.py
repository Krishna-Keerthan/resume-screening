"""
app/services/__init__.py

Service layer exports.

Each service is a stateless class whose constructor accepts only
repositories and config.  All I/O (DB, ML inference, LLM calls) goes
through the service layer — API handlers are thin.

Import order matches dependency graph (no circular imports):
  infrastructure → parsing → scoring → analysis → recommendations
"""

# ── Infrastructure singletons ─────────────────────────────────────────────────
from app.services.embedding_service import EmbeddingService
from app.services.groq_service import GroqService

# ── Parsing ───────────────────────────────────────────────────────────────────
from app.services.resume_parser import ResumeParserService
from app.services.job_parser import JobParserService

# ── Core scoring pipeline ─────────────────────────────────────────────────────
from app.services.keyword_matcher import KeywordMatcherService
from app.services.semantic_matcher import SemanticMatcherService
from app.services.experience_scorer import ExperienceScorerService
from app.services.section_quality_scorer import SectionQualityScorerService
from app.services.ats_scorer import AtsScorerService

# ── Explainability ────────────────────────────────────────────────────────────
from app.services.explainability_engine import ExplainabilityEngine

# ── High-level analysis ───────────────────────────────────────────────────────
from app.services.resume_analysis_service import ResumeAnalysisService
from app.services.smart_job_posting_service import SmartJobPostingService

# ── Recommendations ───────────────────────────────────────────────────────────
from app.services.job_recommendation_service import JobRecommendationService
from app.services.candidate_ranking_service import CandidateRankingService

# ── Analytics ─────────────────────────────────────────────────────────────────
from app.services.recruiter_analytics_service import RecruiterAnalyticsService

__all__ = [
    "EmbeddingService",
    "GroqService",
    "ResumeParserService",
    "JobParserService",
    "KeywordMatcherService",
    "SemanticMatcherService",
    "ExperienceScorerService",
    "SectionQualityScorerService",
    "AtsScorerService",
    "ExplainabilityEngine",
    "ResumeAnalysisService",
    "SmartJobPostingService",
    "JobRecommendationService",
    "CandidateRankingService",
    "RecruiterAnalyticsService",
]