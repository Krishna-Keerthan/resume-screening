"""
tests/unit/test_ats_scorer.py  —  AtsScorerService orchestration.

Uses the `ats_scorer` fixture: real scorers and repository, stubbed
embedding model.
"""


def test_scores_and_persists(ats_scorer, sample_resume, sample_job):
    result = ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
    assert result.error is None
    assert result.ats_score_id is not None
    assert 0.0 < result.final_score <= 1.0


def test_scorer_exception_sets_error(ats_scorer, sample_resume, sample_job, monkeypatch):
    def broken_score(**kwargs):
        raise RuntimeError("experience scorer down")

    monkeypatch.setattr(ats_scorer._exp, "score", broken_score)
    result = ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
    assert result.error == "experience scorer down"


def test_oov_skills_reach_keyword_scorer(ats_scorer, sample_resume, sample_job, monkeypatch):
    sample_resume.oov_skills_list_parsed = ["Temporal"]
    seen = {}
    real_score = ats_scorer._kw.score

    def spy(**kwargs):
        seen.update(kwargs)
        return real_score(**kwargs)

    monkeypatch.setattr(ats_scorer._kw, "score", spy)
    ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
    assert seen["oov_skills"] == ["Temporal"]


class TestPreviewMatchesSavedScore:
    """Preview endpoints must report the same final_score that gets saved."""

    def _use_real_scorer(self, mock_services, ats_scorer):
        mock_services.ats_scorer = ats_scorer
        mock_services.explainability = ats_scorer._expl

    def test_resume_score_preview(self, client, ats_scorer, mock_services,
                                  sample_resume, sample_job):
        sample_resume.oov_skills_list_parsed = ["Flask-RESTX"]
        self._use_real_scorer(mock_services, ats_scorer)
        r = client.get(f"/api/v1/resumes/{sample_resume.id}/score-preview?job_id={sample_job.id}")
        assert r.status_code == 200
        saved = ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
        assert r.get_json()["data"]["final_score"] == saved.final_score

    def test_scores_match_preview(self, client, json_post, ats_scorer, mock_services,
                                  sample_resume, sample_job):
        sample_resume.oov_skills_list_parsed = ["Flask-RESTX"]
        self._use_real_scorer(mock_services, ats_scorer)
        r, body = json_post("/api/v1/scores/match", {
            "resume_id": sample_resume.id, "job_id": sample_job.id, "save_result": False,
        })
        assert r.status_code == 200
        saved = ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
        assert body["data"]["final_score"] == saved.final_score
