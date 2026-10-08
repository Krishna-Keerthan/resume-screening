"""
tests/integration/test_scoring_real_model.py

End-to-end ATS scoring with the real MiniLM embedding model.
Downloads the model on first run; run with: pytest --run-slow -m slow
"""
import pytest


@pytest.mark.slow
def test_real_model_scores_matching_pair(app, ats_scorer, sample_resume, sample_job,
                                         sample_recruiter):
    from app.models.enums import JobStatus, JobType
    from app.models.job import Job
    from app.services.embedding_service import EmbeddingService
    from app.services.semantic_matcher import SemanticMatcherService

    embedding = EmbeddingService.get_instance(
        model_name=app.config["EMBEDDING_MODEL"],
        cache_dir=app.config["EMBEDDING_CACHE_DIR"],
    )
    assert embedding._ensure_loaded(), "embedding model failed to load"
    ats_scorer._sem = SemanticMatcherService(embedding_service=embedding)

    unrelated = Job(
        title="Pastry Chef",
        company="Le Petit Four",
        description=(
            "Bake croissants, laminated doughs and plated desserts for a busy "
            "French patisserie. Pastry school diploma preferred."
        ),
        experience_years=5.0,
        location="Paris",
        job_type=JobType.FULL_TIME,
        status=JobStatus.ACTIVE,
        recruiter_id=sample_recruiter.id,
    )
    unrelated.required_skills_list = ["Baking", "Lamination", "Plating"]
    unrelated.save()

    match = ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
    mismatch = ats_scorer.score_resume_job(sample_resume, unrelated, use_llm=False)

    assert match.error is None
    assert match.semantic_available is True
    assert 0.6 <= match.final_score <= 1.0
    assert match.score_label in ("good", "excellent")
    assert match.semantic_score > mismatch.semantic_score
    assert match.final_score > mismatch.final_score
