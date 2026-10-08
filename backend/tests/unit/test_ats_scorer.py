"""
tests/unit/test_ats_scorer.py  —  AtsScorerService orchestration.

Uses the real keyword / experience / section-quality scorers and the real
AtsScore repository; only the embedding-backed semantic matcher is stubbed.
"""
import pytest

from app.services.semantic_matcher import SemanticScoreResult


class _UnavailableSemantic:
    """Behaves like SemanticMatcherService when the embedding model is not loaded."""

    def score(self, **kwargs):
        return SemanticScoreResult(score=0.0, raw_cosine=0.0, available=False)


@pytest.fixture
def scorer(db):
    from app.repositories import AtsScoreRepository
    from app.services.ats_scorer import AtsScorerService
    from app.services.experience_scorer import ExperienceScorerService
    from app.services.explainability_engine import ExplainabilityEngine
    from app.services.keyword_matcher import KeywordMatcherService
    from app.services.section_quality_scorer import SectionQualityScorerService

    keyword_matcher = KeywordMatcherService()
    return AtsScorerService(
        keyword_matcher=keyword_matcher,
        semantic_matcher=_UnavailableSemantic(),
        experience_scorer=ExperienceScorerService(),
        section_quality_scorer=SectionQualityScorerService(),
        explainability_engine=ExplainabilityEngine(keyword_matcher=keyword_matcher),
        ats_score_repo=AtsScoreRepository(),
    )


def test_scores_and_persists(scorer, sample_resume, sample_job):
    result = scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
    assert result.error is None
    assert result.ats_score_id is not None
    assert 0.0 < result.final_score <= 1.0


def test_scorer_exception_sets_error(scorer, sample_resume, sample_job, monkeypatch):
    def broken_score(**kwargs):
        raise RuntimeError("experience scorer down")

    monkeypatch.setattr(scorer._exp, "score", broken_score)
    result = scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
    assert result.error == "experience scorer down"


def test_oov_skills_reach_keyword_scorer(scorer, sample_resume, sample_job, monkeypatch):
    sample_resume.oov_skills_list_parsed = ["Temporal"]
    seen = {}
    real_score = scorer._kw.score

    def spy(**kwargs):
        seen.update(kwargs)
        return real_score(**kwargs)

    monkeypatch.setattr(scorer._kw, "score", spy)
    scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
    assert seen["oov_skills"] == ["Temporal"]
