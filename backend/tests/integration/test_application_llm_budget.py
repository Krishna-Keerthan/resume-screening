"""
POST /applications/ runs its scoring and its improvement plan inside one Groq time budget.
"""
from types import SimpleNamespace

from app.services.groq_service import remaining_budget

BASE = "/api/v1/applications"


def test_both_groq_calls_run_inside_the_request_budget(
    app, db, json_post, job_a, resume_a, candidate_a, headers_for, mock_services
):
    seen = {}

    def score(**kwargs):
        seen["scoring"] = remaining_budget()
        return SimpleNamespace(error=None, final_score=0.40, score_label="weak",
                               missing_skills=[], matched_skills=[])

    def plan(**kwargs):
        seen["plan"] = remaining_budget()
        return {"plan": []}

    mock_services.ats_scorer.score_resume_job.side_effect = score
    mock_services.groq.generate_improvement_plan.side_effect = plan

    r, _ = json_post(f"{BASE}/", {"job_id": job_a.id, "resume_id": resume_a.id}, headers=headers_for(candidate_a))

    assert r.status_code == 201
    budget = app.config["GROQ_CALL_BUDGET_SECONDS"]
    assert budget - 5 < seen["scoring"] <= budget
    assert budget - 5 < seen["plan"] <= budget
    assert remaining_budget() is None          # the budget ends with the request
