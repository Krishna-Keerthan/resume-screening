"""
tests/integration/test_scoring.py

Integration tests for /api/v1/scores/* endpoints.

  POST /scores/match            — a candidate for their own resume against an active job,
                                  or a recruiter for their own job and a resume submitted to it
  POST /scores/job-recommendations — a candidate, for their own resume
  GET  /scores/<id>             — the resume's candidate, or the job's recruiter
"""
import pytest
from unittest.mock import MagicMock, create_autospec

BASE = "/api/v1/scores"


def _score_result():
    from app.services.ats_scorer import ScoringResult
    return ScoringResult(
        resume_id="r-id",
        job_id="j-id",
        final_score=0.78,
        score_label="good",
        semantic_score=0.70,
        keyword_score=0.80,
        experience_score=0.75,
        section_quality_score=0.65,
        semantic_available=True,
        matched_skills=["Python", "Flask"],
        missing_skills=["Kubernetes"],
        extra_skills=["FastAPI"],
        ats_score_id="mock-ats-id",
    )


def _raw_score():
    """Same keys AtsScorerService.score_raw returns."""
    return {
        "final_score": 0.75, "semantic_score": 0.0, "keyword_score": 0.8,
        "experience_score": 0.7, "section_quality_score": 0.6,
        "semantic_available": False, "semantic_component_scores": {},
        "weights_used": {"semantic": 0.4, "keyword": 0.35, "experience": 0.15, "section": 0.1},
    }


def _routes(app):
    return {(method, rule.rule) for rule in app.url_map.iter_rules() for method in rule.methods}


@pytest.fixture()
def draft_job_a(db, job_a):
    job_a.status = "draft"
    db.session.commit()
    return job_a


@pytest.fixture()
def score_a(db, resume_a, job_a):
    from app.models.ats_score import AtsScore
    s = AtsScore(resume_id=resume_a.id, job_id=job_a.id)
    s.save()
    db.session.commit()
    return s


class TestRemovedRoutes:
    @pytest.mark.parametrize("method, rule", [
        ("POST", f"{BASE}/rank-candidates"),
        ("POST", f"{BASE}/skill-gap"),
        ("GET", f"{BASE}/"),
    ])
    def test_route_is_gone(self, app, method, rule):
        assert (method, rule) not in _routes(app)


class TestMatchEndpoint:
    @staticmethod
    def _body(resume, job, **extra):
        return {"resume_id": resume.id, "job_id": job.id, "save_result": False, **extra}

    def test_candidate_access_rules(
        self, check_access, resume_a, job_a, candidate_a, candidate_b, mock_services
    ):
        mock_services.ats_scorer.score_raw.return_value = _raw_score()
        r = check_access("POST", f"{BASE}/match", owner=candidate_a, other=candidate_b,
                         json=self._body(resume_a, job_a))
        assert r.get_json()["data"]["saved"] is False

    def test_recruiter_access_rules(
        self, check_access, application_a, resume_a, job_a, recruiter_a, recruiter_b, mock_services
    ):
        mock_services.ats_scorer.score_raw.return_value = _raw_score()
        check_access("POST", f"{BASE}/match", owner=recruiter_a, other=recruiter_b,
                     json=self._body(resume_a, job_a))

    def test_recruiter_cannot_score_a_resume_that_was_not_submitted_to_their_job(
        self, client, db, application_a, resume_b, job_a, recruiter_a, headers_for, mock_services
    ):
        r = client.post(f"{BASE}/match", json=self._body(resume_b, job_a), headers=headers_for(recruiter_a))
        assert r.status_code == 403
        mock_services.ats_scorer.score_raw.assert_not_called()

    def test_candidate_cannot_score_someone_elses_resume(
        self, client, db, resume_b, job_a, candidate_a, headers_for, mock_services
    ):
        r = client.post(f"{BASE}/match", json=self._body(resume_b, job_a), headers=headers_for(candidate_a))
        assert r.status_code == 403
        mock_services.ats_scorer.score_raw.assert_not_called()

    def test_candidate_gets_404_for_a_job_that_is_not_active(
        self, client, db, resume_a, draft_job_a, candidate_a, headers_for, mock_services
    ):
        r = client.post(f"{BASE}/match", json=self._body(resume_a, draft_job_a), headers=headers_for(candidate_a))
        assert r.status_code == 404

    def test_preview_calls_score_raw_with_its_real_signature(
        self, client, db, resume_a, job_a, candidate_a, headers_for, mock_services,
    ):
        from app.services.ats_scorer import AtsScorerService
        mock_services.ats_scorer = create_autospec(AtsScorerService, instance=True)
        mock_services.ats_scorer.score_raw.return_value = _raw_score()
        r = client.post(f"{BASE}/match", json=self._body(resume_a, job_a), headers=headers_for(candidate_a))
        assert r.status_code == 200
        kwargs = mock_services.ats_scorer.score_raw.call_args.kwargs
        assert kwargs["job_experience_years"] == job_a.experience_years

    def test_persist_mode(self, client, db, resume_a, job_a, candidate_a, headers_for, mock_services):
        mock_services.ats_scorer.score_resume_job.return_value = _score_result()
        r = client.post(f"{BASE}/match", json=self._body(resume_a, job_a, save_result=True),
                        headers=headers_for(candidate_a))
        assert r.status_code in (200, 201)
        assert r.get_json()["data"]["saved"] is True

    def test_missing_resume_id_400(self, client, db, job_a, candidate_a, headers_for, mock_services):
        r = client.post(f"{BASE}/match", json={"job_id": job_a.id}, headers=headers_for(candidate_a))
        assert r.status_code == 400

    def test_missing_job_id_400(self, client, db, resume_a, candidate_a, headers_for, mock_services):
        r = client.post(f"{BASE}/match", json={"resume_id": resume_a.id}, headers=headers_for(candidate_a))
        assert r.status_code == 400

    def test_nonexistent_resume_404(self, client, db, job_a, candidate_a, headers_for, mock_services):
        r = client.post(f"{BASE}/match", json={"resume_id": "no-such-resume", "job_id": job_a.id},
                        headers=headers_for(candidate_a))
        assert r.status_code == 404

    def test_nonexistent_job_404(self, client, db, resume_a, candidate_a, headers_for, mock_services):
        r = client.post(f"{BASE}/match", json={"resume_id": resume_a.id, "job_id": "no-such-job"},
                        headers=headers_for(candidate_a))
        assert r.status_code == 404


class TestJobRecommendationsEndpoint:
    def test_access_rules(self, check_access, resume_a, candidate_a, candidate_b, mock_services):
        mock_services.job_recommendations.recommend.return_value = []
        r = check_access("POST", f"{BASE}/job-recommendations", owner=candidate_a, other=candidate_b,
                         json={"resume_id": resume_a.id, "top_n": 5})
        assert r.get_json()["data"]["total"] == 0

    def test_recommend_receives_the_callers_resume(
        self, client, db, resume_a, candidate_a, headers_for, mock_services
    ):
        mock_services.job_recommendations.recommend.return_value = []
        client.post(f"{BASE}/job-recommendations", json={"resume_id": resume_a.id, "top_n": 3},
                    headers=headers_for(candidate_a))
        kwargs = mock_services.job_recommendations.recommend.call_args.kwargs
        assert kwargs["resume"].id == resume_a.id
        assert kwargs["top_n"] == 3

    def test_a_recruiter_gets_403(self, client, db, resume_a, recruiter_a, headers_for, mock_services):
        r = client.post(f"{BASE}/job-recommendations", json={"resume_id": resume_a.id},
                        headers=headers_for(recruiter_a))
        assert r.status_code == 403

    def test_unparsed_resume_422(self, client, db, resume_a, candidate_a, headers_for, mock_services):
        resume_a.parse_status = "pending"
        db.session.commit()
        r = client.post(f"{BASE}/job-recommendations", json={"resume_id": resume_a.id},
                        headers=headers_for(candidate_a))
        assert r.status_code == 422

    def test_nonexistent_resume_404(self, client, db, candidate_a, headers_for, mock_services):
        r = client.post(f"{BASE}/job-recommendations", json={"resume_id": "no-such"},
                        headers=headers_for(candidate_a))
        assert r.status_code == 404

    def test_missing_resume_id_400(self, client, db, candidate_a, headers_for, mock_services):
        r = client.post(f"{BASE}/job-recommendations", json={}, headers=headers_for(candidate_a))
        assert r.status_code == 400


class TestGetScore:
    def test_candidate_access_rules(self, check_access, score_a, candidate_a, candidate_b):
        r = check_access("GET", f"{BASE}/{score_a.id}", owner=candidate_a, other=candidate_b)
        assert r.get_json()["data"]["id"] == score_a.id

    def test_recruiter_access_rules(self, check_access, score_a, recruiter_a, recruiter_b):
        check_access("GET", f"{BASE}/{score_a.id}", owner=recruiter_a, other=recruiter_b)

    def test_nonexistent_404(self, client, db, candidate_a, headers_for):
        r = client.get(f"{BASE}/no-such-score", headers=headers_for(candidate_a))
        assert r.status_code == 404
        assert r.get_json()["error"]["error_code"] == "SCORE_NOT_FOUND"
