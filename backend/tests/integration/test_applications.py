
"""
tests/integration/test_applications.py

Integration tests for /api/v1/applications/* endpoints.
Tests business rules: duplicate guard, inactive job guard, ownership guard, stage transitions.
"""
import json
import uuid
import pytest

BASE = "/api/v1/applications"


class TestListApplications:
    def test_returns_200(self, client, db):
        assert client.get(f"{BASE}/").status_code == 200

    def test_success_envelope(self, client, db):
        assert client.get(f"{BASE}/").get_json()["success"] is True

    def test_data_is_list(self, client, db):
        assert isinstance(client.get(f"{BASE}/").get_json()["data"], list)

    def test_filter_by_job_id(self, client, db, sample_application, sample_job):
        body = client.get(f"{BASE}/?job_id={sample_job.id}").get_json()
        ids = [a["id"] for a in body["data"]]
        assert sample_application.id in ids

    def test_filter_by_candidate_id(self, client, db, sample_application, sample_candidate):
        body = client.get(f"{BASE}/?candidate_id={sample_candidate.id}").get_json()
        ids = [a["id"] for a in body["data"]]
        assert sample_application.id in ids

    def test_filter_by_stage(self, client, db, sample_application):
        body = client.get(f"{BASE}/?candidate_id={sample_application.candidate_id}&stage=applied").get_json()
        assert all(a["stage"] == "applied" for a in body["data"])


class TestCreateApplication:
    def _payload(self, candidate_id, job_id, resume_id):
        return {"candidate_id": candidate_id, "job_id": job_id, "resume_id": resume_id}

    def test_returns_201(self, client, db, json_post,
                         sample_candidate, sample_job, sample_resume, mock_services):
        mock_services.ats_scorer.score_resume_job.return_value.error = None
        mock_services.ats_scorer.score_resume_job.return_value.final_score = 0.75
        mock_services.ats_scorer.score_resume_job.return_value.score_label = "good"

        r, _ = json_post(f"{BASE}/", self._payload(
            sample_candidate.id, sample_job.id, sample_resume.id))
        assert r.status_code == 201

    def test_stage_is_applied(self, client, db, json_post,
                              sample_candidate, sample_job, sample_resume, mock_services):
        mock_services.ats_scorer.score_resume_job.return_value.error = None
        _, body = json_post(f"{BASE}/", self._payload(
            sample_candidate.id, sample_job.id, sample_resume.id))
        assert body["data"]["stage"] == "applied"

    def test_duplicate_application_409(self, client, db, json_post, sample_application, mock_services):
        r, body = json_post(f"{BASE}/", self._payload(
            sample_application.candidate_id,
            sample_application.job_id,
            sample_application.resume_id,
        ))
        assert r.status_code == 409
        assert body["error"]["error_code"] == "DUPLICATE_APPLICATION"

    def test_inactive_job_422(self, client, db, json_post,
                              sample_candidate, sample_job_closed, sample_resume, mock_services):
        r, body = json_post(f"{BASE}/", self._payload(
            sample_candidate.id, sample_job_closed.id, sample_resume.id))
        assert r.status_code == 422
        assert body["error"]["error_code"] == "JOB_NOT_ACTIVE"

    def test_nonexistent_candidate_404(self, client, db, json_post,
                                       sample_job, sample_resume, mock_services):
        r, _ = json_post(f"{BASE}/", self._payload(
            str(uuid.uuid4()), sample_job.id, sample_resume.id))
        assert r.status_code == 404

    def test_nonexistent_job_404(self, client, db, json_post,
                                 sample_candidate, sample_resume, mock_services):
        r, _ = json_post(f"{BASE}/", self._payload(
            sample_candidate.id, str(uuid.uuid4()), sample_resume.id))
        assert r.status_code == 404

    def test_nonexistent_resume_404(self, client, db, json_post,
                                    sample_candidate, sample_job, mock_services):
        r, _ = json_post(f"{BASE}/", self._payload(
            sample_candidate.id, sample_job.id, str(uuid.uuid4())))
        assert r.status_code == 404

    def test_resume_ownership_mismatch_403(self, client, db, json_post,
                                            sample_job, sample_resume, mock_services):
        # Create a second candidate and try to apply using first candidate's resume
        from app.models.candidate import Candidate
        from app.core.database import db as _db
        with db.session.begin_nested():
            other = Candidate(
                full_name="Other Person",
                email=f"other+{uuid.uuid4().hex[:6]}@test.com",
            )
            other.save()
            _db.session.flush()

        r, body = json_post(f"{BASE}/", {
            "candidate_id": other.id,
            "job_id":       sample_job.id,
            "resume_id":    sample_resume.id,   # belongs to sample_candidate, not other
        })
        assert r.status_code == 403
        assert body["error"]["error_code"] == "RESUME_OWNERSHIP_MISMATCH"

    def test_missing_fields_400(self, client, db, json_post, mock_services):
        r, _ = json_post(f"{BASE}/", {"candidate_id": "x"})
        assert r.status_code == 400


class TestGetApplication:
    def test_returns_200(self, client, db, sample_application):
        assert client.get(f"{BASE}/{sample_application.id}").status_code == 200

    def test_correct_data(self, client, db, sample_application):
        body = client.get(f"{BASE}/{sample_application.id}").get_json()
        assert body["data"]["id"] == sample_application.id
        assert body["data"]["stage"] == "applied"

    def test_nonexistent_404(self, client, db):
        assert client.get(f"{BASE}/phantom-app").status_code == 404


class TestUpdateApplicationStage:
    def test_advance_to_reviewed(self, client, db, sample_application, json_patch):
        r, body = json_patch(
            f"{BASE}/{sample_application.id}/stage",
            {"stage": "reviewed"},
        )
        assert r.status_code == 200
        assert body["data"]["stage"] == "reviewed"

    def test_recruiter_notes_saved(self, client, db, sample_application, json_patch):
        _, body = json_patch(
            f"{BASE}/{sample_application.id}/stage",
            {"stage": "reviewed", "recruiter_notes": "Strong candidate, move forward."},
        )
        assert body["data"]["recruiter_notes"] == "Strong candidate, move forward."

    def test_rejection_reason_saved(self, client, db, sample_application, json_patch):
        _, body = json_patch(
            f"{BASE}/{sample_application.id}/stage",
            {"stage": "rejected", "rejection_reason": "Overqualified."},
        )
        assert body["data"]["rejection_reason"] == "Overqualified."

    def test_invalid_stage_400(self, client, db, sample_application, json_patch):
        r, _ = json_patch(
            f"{BASE}/{sample_application.id}/stage",
            {"stage": "flying"},
        )
        assert r.status_code == 400

    def test_nonexistent_404(self, client, db, json_patch):
        r, _ = json_patch(f"{BASE}/ghost/stage", {"stage": "reviewed"})
        assert r.status_code == 404


class TestWithdrawApplication:
    def test_returns_204(self, client, db, sample_application):
        assert client.delete(f"{BASE}/{sample_application.id}").status_code == 204

    def test_after_withdraw_stage_is_withdrawn(self, client, db, sample_application, json_patch):
        # Manually set to hired to test block
        json_patch(f"{BASE}/{sample_application.id}/stage", {"stage": "reviewed"})
        # Now withdraw
        client.delete(f"{BASE}/{sample_application.id}")
        body = client.get(f"{BASE}/{sample_application.id}").get_json()
        assert body["data"]["stage"] == "withdrawn"

    def test_cannot_withdraw_hired(self, client, db, sample_application, json_patch):
        # Advance all the way to hired
        for stage in ["reviewed", "shortlisted", "interviewing", "offered", "hired"]:
            json_patch(f"{BASE}/{sample_application.id}/stage", {"stage": stage})

        r = client.delete(f"{BASE}/{sample_application.id}")
        assert r.status_code == 422
        assert r.get_json()["error"]["error_code"] == "CANNOT_WITHDRAW"

    def test_nonexistent_404(self, client, db):
        assert client.delete(f"{BASE}/no-such-app").status_code == 404