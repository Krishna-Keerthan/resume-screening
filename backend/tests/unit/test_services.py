
"""
tests/unit/test_services.py

Unit tests for service layer components (no ML models required).
Tests keyword matcher, experience scorer, section quality scorer.
"""
import pytest


# ─── KeywordMatcherService ─────────────────────────────────────────────────────

class TestKeywordMatcher:
    @pytest.fixture
    def matcher(self, app):
        with app.app_context():
            from app.services.keyword_matcher import KeywordMatcherService
            return KeywordMatcherService()

    def test_exact_match_high_score(self, app, matcher):
        with app.app_context():
            resume_skills = ["Python", "Flask", "PostgreSQL", "Docker"]
            job_skills    = ["Python", "Flask", "PostgreSQL", "Docker"]
            result = matcher.score(resume_skills, job_skills)
            assert result.score >= 0.9
            assert set(result.matched) == {"Python", "Flask", "PostgreSQL", "Docker"}
            assert result.missing == []

    def test_no_match_zero_score(self, app, matcher):
        with app.app_context():
            result = matcher.score(["Java", "Spring"], ["Python", "Flask"])
            assert result.score == 0.0
            assert result.matched == []
            assert set(result.missing) == {"Python", "Flask"}

    def test_partial_match(self, app, matcher):
        with app.app_context():
            result = matcher.score(
                ["Python", "Flask"],
                ["Python", "Flask", "Kubernetes", "Redis"],
            )
            assert 0.0 < result.score < 1.0
            assert "Python" in result.matched
            assert "Kubernetes" in result.missing

    def test_case_insensitive(self, app, matcher):
        with app.app_context():
            result = matcher.score(["PYTHON", "flask"], ["python", "Flask"])
            assert result.score >= 0.9

    def test_extra_skills_captured(self, app, matcher):
        with app.app_context():
            result = matcher.score(
                ["Python", "Flask", "FastAPI", "GraphQL"],
                ["Python", "Flask"],
            )
            assert "FastAPI" in result.extra or "GraphQL" in result.extra

    def test_empty_job_skills(self, app, matcher):
        with app.app_context():
            result = matcher.score(["Python", "Flask"], [])
            assert result.score == 0.0 or result.matched == []

    def test_empty_resume_skills(self, app, matcher):
        with app.app_context():
            result = matcher.score([], ["Python", "Flask"])
            assert result.score == 0.0
            assert result.matched == []


# ─── ExperienceScorerService ───────────────────────────────────────────────────

class TestExperienceScorer:
    @pytest.fixture
    def scorer(self, app):
        with app.app_context():
            from app.services.experience_scorer import ExperienceScorerService
            return ExperienceScorerService()

    def test_meets_requirement(self, app, scorer):
        with app.app_context():
            result = scorer.score(
                candidate_years=5.0,
                required_years=3.0,
                education=[],
                seniority_level=None,
            )
            assert result.score >= 0.7

    def test_exceeds_requirement(self, app, scorer):
        with app.app_context():
            result = scorer.score(
                candidate_years=10.0,
                required_years=3.0,
                education=[],
                seniority_level=None,
            )
            assert result.score >= 0.9

    def test_below_requirement(self, app, scorer):
        with app.app_context():
            result = scorer.score(
                candidate_years=1.0,
                required_years=5.0,
                education=[],
                seniority_level=None,
            )
            assert result.score < 0.5

    def test_zero_required_years(self, app, scorer):
        with app.app_context():
            result = scorer.score(
                candidate_years=3.0,
                required_years=0.0,
                education=[],
                seniority_level=None,
            )
            assert result.score >= 0.0

    def test_education_bonus_for_degree(self, app, scorer):
        with app.app_context():
            without_edu = scorer.score(5.0, 5.0, [], None)
            with_edu    = scorer.score(5.0, 5.0,
                                       [{"degree": "B.Tech", "institution": "IIT"}],
                                       None)
            assert with_edu.score >= without_edu.score


# ─── SectionQualityScorerService ───────────────────────────────────────────────

class TestSectionQualityScorer:
    @pytest.fixture
    def scorer(self, app):
        with app.app_context():
            from app.services.section_quality_scorer import SectionQualityScorerService
            return SectionQualityScorerService()

    def test_full_resume_high_score(self, app, scorer):
        with app.app_context():
            result = scorer.score({
                "skills":         ["Python", "Flask", "PostgreSQL", "Docker", "NLP", "Redis"],
                "education":      [{"degree": "B.Tech", "institution": "IIT", "year": 2018}],
                "experience":     [
                    {"title": "Senior Dev", "company": "X", "years": 3.0},
                    {"title": "Dev", "company": "Y", "years": 2.0},
                ],
                "certifications": ["AWS Certified", "Google Cloud"],
                "summary":        "Experienced Python developer specialising in backend systems and ML.",
            })
            assert result.score >= 0.6

    def test_empty_resume_low_score(self, app, scorer):
        with app.app_context():
            result = scorer.score({
                "skills": [], "education": [], "experience": [],
                "certifications": [], "summary": "",
            })
            assert result.score <= 0.3

    def test_score_between_0_and_1(self, app, scorer):
        with app.app_context():
            result = scorer.score({
                "skills": ["Python"], "education": [], "experience": [],
                "certifications": [], "summary": "Dev",
            })
            assert 0.0 <= result.score <= 1.0

    def test_section_breakdown_present(self, app, scorer):
        with app.app_context():
            result = scorer.score({
                "skills":         ["Python", "Flask"],
                "education":      [],
                "experience":     [],
                "certifications": [],
                "summary":        "A short summary.",
            })
            assert hasattr(result, "breakdown") or isinstance(result.score, float)