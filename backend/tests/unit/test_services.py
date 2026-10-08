"""
tests/unit/test_services.py

Unit tests for service layer components (no ML models required).
Tests keyword matcher, experience scorer, section quality scorer.
"""
import pytest


# ─── KeywordMatcherService ─────────────────────────────────────────────────────

class TestKeywordMatcher:
    @pytest.fixture
    def matcher(self):
        from app.services.keyword_matcher import KeywordMatcherService
        return KeywordMatcherService()

    @staticmethod
    def _score(matcher, resume_skills, job_skills):
        return matcher.score(
            resume_text="",
            resume_skills=resume_skills,
            job_description="",
            job_required_skills=job_skills,
        )

    def test_exact_match_scores_above_partial_and_none(self, matcher):
        job = ["Python", "Flask", "Kubernetes", "Redis"]
        exact = self._score(matcher, job, job)
        partial = self._score(matcher, ["Python", "Flask"], job)
        none = self._score(matcher, ["Java", "Spring"], job)
        assert exact > partial > none

    def test_exact_match_breakdown(self, matcher):
        skills = ["Python", "Flask", "PostgreSQL", "Docker"]
        breakdown = matcher.get_skill_breakdown(skills, skills)
        assert len(breakdown["matched"]) == 4
        assert breakdown["missing"] == []

    @pytest.mark.xfail(strict=True, reason=(
        "Phase 4: single-document BM25 has negative IDF and sigmoid(0)=0.5, "
        "so no overlap scores 0.3 and an exact match's BM25 is below no match's"
    ))
    def test_no_match_zero_score(self, matcher):
        assert self._score(matcher, ["Java", "Spring"], ["Python", "Flask"]) == 0.0

    def test_no_match_breakdown(self, matcher):
        breakdown = matcher.get_skill_breakdown(["Java", "Spring"], ["Python", "Flask"])
        assert breakdown["matched"] == []
        assert set(breakdown["missing"]) == {"python", "flask"}

    def test_partial_match(self, matcher):
        resume, job = ["Python", "Flask"], ["Python", "Flask", "Kubernetes", "Redis"]
        assert 0.0 < self._score(matcher, resume, job) < 1.0
        breakdown = matcher.get_skill_breakdown(resume, job)
        assert "python" in breakdown["matched"]
        assert "kubernetes" in breakdown["missing"]

    def test_case_insensitive(self, matcher):
        assert (self._score(matcher, ["PYTHON", "flask"], ["python", "Flask"])
                == self._score(matcher, ["python", "flask"], ["python", "flask"]))

    def test_extra_skills_captured(self, matcher):
        breakdown = matcher.get_skill_breakdown(
            ["Python", "Flask", "FastAPI", "GraphQL"], ["Python", "Flask"],
        )
        assert "fastapi" in breakdown["extra"] or "graphql" in breakdown["extra"]

    def test_empty_job_skills(self, matcher):
        assert self._score(matcher, ["Python", "Flask"], []) == 0.0

    def test_empty_resume_skills(self, matcher):
        assert self._score(matcher, [], ["Python", "Flask"]) == 0.0
        assert matcher.get_skill_breakdown([], ["Python", "Flask"])["matched"] == []


# ─── ExperienceScorerService ───────────────────────────────────────────────────

class TestExperienceScorer:
    @pytest.fixture
    def scorer(self):
        from app.services.experience_scorer import ExperienceScorerService
        return ExperienceScorerService()

    def test_meets_requirement(self, scorer):
        assert scorer.score(candidate_years=5.0, required_years=3.0) >= 0.7

    def test_exceeds_requirement(self, scorer):
        assert scorer.score(candidate_years=10.0, required_years=3.0) >= 0.9

    def test_below_requirement(self, scorer):
        assert scorer.score(candidate_years=1.0, required_years=5.0) < 0.5

    def test_zero_required_years(self, scorer):
        assert scorer.score(candidate_years=3.0, required_years=0.0) >= 0.0

    def test_education_bonus_for_degree(self, scorer):
        without_edu = scorer.score(candidate_years=4.0, required_years=5.0, education=[])
        with_edu = scorer.score(
            candidate_years=4.0, required_years=5.0,
            education=[{"degree": "B.Sc Computer Science", "institution": "IIT"}],
        )
        assert with_edu > without_edu

    @pytest.mark.xfail(strict=True, reason=(
        "Phase 4: degree regex misses B.Tech, BE, M.Tech and MCA"
    ))
    def test_education_bonus_for_btech(self, scorer):
        without_edu = scorer.score(candidate_years=4.0, required_years=5.0, education=[])
        with_edu = scorer.score(
            candidate_years=4.0, required_years=5.0,
            education=[{"degree": "B.Tech", "institution": "IIT"}],
        )
        assert with_edu > without_edu


# ─── SectionQualityScorerService ───────────────────────────────────────────────

class TestSectionQualityScorer:
    @pytest.fixture
    def scorer(self):
        from app.services.section_quality_scorer import SectionQualityScorerService
        return SectionQualityScorerService()

    def test_full_resume_high_score(self, scorer):
        score = scorer.score(
            skills=["Python", "Flask", "PostgreSQL", "Docker", "NLP", "Redis"],
            education=[{"degree": "B.Tech", "institution": "IIT", "year": 2018}],
            experience=[
                {"title": "Senior Dev", "company": "X", "years": 3.0},
                {"title": "Dev", "company": "Y", "years": 2.0},
            ],
            certifications=["AWS Certified", "Google Cloud"],
            summary_text="Experienced Python developer specialising in backend systems and ML.",
        )
        assert score >= 0.6

    def test_empty_resume_low_score(self, scorer):
        score = scorer.score(
            skills=[], education=[], experience=[], certifications=[], summary_text="",
        )
        assert score <= 0.3

    def test_score_between_0_and_1(self, scorer):
        score = scorer.score(
            skills=["Python"], education=[], experience=[], certifications=[],
            summary_text="Dev",
        )
        assert 0.0 <= score <= 1.0

    def test_section_breakdown_present(self, scorer):
        breakdown = scorer.get_breakdown(
            skills=["Python", "Flask"], education=[], experience=[],
            certifications=[], summary_text="A short summary.",
        )
        assert set(breakdown) == {
            "has_skills", "has_experience", "has_education", "has_summary",
            "has_certifications", "has_projects", "sufficient_length",
        }
        assert all(satisfied is False for satisfied, _ in breakdown.values())
