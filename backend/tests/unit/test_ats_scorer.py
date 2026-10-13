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

    def test_resume_score_preview(self, client, ats_scorer, mock_services, headers_for,
                                  sample_candidate, sample_resume, sample_job):
        sample_resume.oov_skills_list_parsed = ["Flask-RESTX"]
        self._use_real_scorer(mock_services, ats_scorer)
        r = client.get(f"/api/v1/resumes/{sample_resume.id}/score-preview?job_id={sample_job.id}",
                       headers=headers_for(sample_candidate))
        assert r.status_code == 200
        saved = ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
        assert r.get_json()["data"]["final_score"] == saved.final_score

    def test_scores_match_preview(self, client, json_post, ats_scorer, mock_services, headers_for,
                                  sample_candidate, sample_resume, sample_job):
        sample_resume.oov_skills_list_parsed = ["Flask-RESTX"]
        self._use_real_scorer(mock_services, ats_scorer)
        r, body = json_post("/api/v1/scores/match", {
            "resume_id": sample_resume.id, "job_id": sample_job.id, "save_result": False,
        }, headers=headers_for(sample_candidate))
        assert r.status_code == 200
        saved = ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
        assert body["data"]["final_score"] == saved.final_score


class TestStoredScores:
    def test_cached_result_keeps_semantic_available(self, ats_scorer, sample_resume, sample_job):
        first = ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
        cached = ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
        assert first.semantic_available is False
        assert cached.from_cache is True
        assert cached.semantic_available is False

    def test_record_build_failure_is_reported(self, ats_scorer, sample_resume, sample_job,
                                              monkeypatch):
        from app.models.ats_score import AtsScore

        def broken(**kwargs):
            raise ValueError("cannot build record")

        monkeypatch.setattr(AtsScore, "from_score_result", broken)
        result = ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
        assert result.error == "cannot build record"

    def test_missing_label_function_is_reported(self, ats_scorer, sample_resume, sample_job,
                                                monkeypatch):
        monkeypatch.delattr("app.models.enums.score_to_label")
        result = ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
        assert result.error is not None
        assert "score_to_label" in result.error

    def test_unreadable_cached_record_is_reported(self, ats_scorer, sample_resume, sample_job,
                                                  monkeypatch):
        from app.models.ats_score import AtsScore
        ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)

        def corrupt(self):
            raise ValueError("corrupt weights_used")

        monkeypatch.setattr(AtsScore, "weights_used_dict", property(corrupt))
        result = ats_scorer.score_resume_job(sample_resume, sample_job, use_llm=False)
        assert result.error == "corrupt weights_used"
