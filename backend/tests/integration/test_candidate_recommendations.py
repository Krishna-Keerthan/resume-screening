"""
tests/integration/test_candidate_recommendations.py

POST /api/v1/candidates/<id>/recommendations
"""
from unittest.mock import create_autospec


def _candidate_auth(candidate):
    from app.core.security import create_tokens
    access_token, _, _ = create_tokens(candidate.id, "candidate")
    return {"Authorization": f"Bearer {access_token}"}


def test_filters_reach_recommendation_service(client, json_post, mock_services,
                                              sample_candidate, sample_resume):
    from app.services.job_recommendation_service import JobRecommendationService
    mock_services.job_recommendations = create_autospec(JobRecommendationService, instance=True)
    mock_services.job_recommendations.recommend.return_value = []

    r, _ = json_post(
        f"/api/v1/candidates/{sample_candidate.id}/recommendations",
        {"top_n": 5, "location": "Remote", "job_type": "full-time"},
        headers=_candidate_auth(sample_candidate),
    )

    assert r.status_code == 200
    kwargs = mock_services.job_recommendations.recommend.call_args.kwargs
    assert kwargs["location_filter"] == "Remote"
    assert kwargs["job_type_filter"] == "full-time"
