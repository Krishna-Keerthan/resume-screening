"""
app/services/experience_scorer.py

Experience scorer — evaluates candidate experience level vs job requirements.

Scoring logic:
  1. Experience years ratio:  min(candidate_years / required_years, 1.5)
     → Normalised to [0, 1].  Overqualification (>1.5x) is capped but not penalised
       since the job could still be interesting to an overqualified candidate.

  2. Education bonus: small bonus for relevant higher education (0.0–0.1).

  3. Seniority check: infers expected years from job title keywords
     (junior/mid/senior/lead) and penalises a large mismatch.

  4. Career gap penalty: if the most recent experience is older than 2 years,
     apply a small penalty (0.0–0.05).

Final score = clamp(base_ratio_score + edu_bonus - gap_penalty, 0.0, 1.0)

Design decisions:
  - Score 0.0 when required_years = 0 but candidate has 0 years (entry level
    match scores 0.5 to avoid false negatives).
  - Score 1.0 when required_years = 0 and candidate has experience.
  - All components are independently tuneable via constructor parameters.

Usage:
    from app.services.experience_scorer import ExperienceScorerService
    svc = ExperienceScorerService()
    score = svc.score(
        candidate_years=4.5,
        required_years=3.0,
        job_title="Senior Python Developer",
        education=[{"degree": "BSc Computer Science"}],
        experience=[{"date_range": "2020 - 2024"}],
    )
"""

import logging
import re

logger = logging.getLogger(__name__)

_SENIOR_TITLE_RE  = re.compile(r"\b(senior|sr\.?|principal|staff|experienced)\b", re.I)
_LEAD_TITLE_RE    = re.compile(r"\b(lead|head|director|vp|chief|architect)\b", re.I)
_JUNIOR_TITLE_RE  = re.compile(r"\b(junior|jr\.?|entry.level|associate|graduate|intern)\b", re.I)
_MID_TITLE_RE     = re.compile(r"\b(mid.?level|middle|intermediate)\b", re.I)

_DEGREE_RE = re.compile(
    r"(bachelor|master|phd|doctorate|b\.?sc?|m\.?sc?|m\.?eng?|b\.?eng?|mba)",
    re.I
)


class ExperienceScorerService:
    """
    Scores candidate experience fit against a job posting.

    All parameters have sensible defaults and can be overridden in tests.
    """

    def __init__(
        self,
        overqualification_cap: float = 1.5,
        edu_bonus_max: float = 0.08,
        gap_penalty_max: float = 0.05,
    ):
        self.overqualification_cap = overqualification_cap
        self.edu_bonus_max = edu_bonus_max
        self.gap_penalty_max = gap_penalty_max

    def score(
        self,
        candidate_years: float,
        required_years: float,
        job_title: str = "",
        education: list[dict] | None = None,
        experience: list[dict] | None = None,
    ) -> float:
        """
        Compute experience fit score.

        Args:
            candidate_years: Total parsed experience years from resume.
            required_years:  Minimum years required from job posting.
            job_title:       Job title (used for seniority inference).
            education:       Parsed education list (for edu bonus).
            experience:      Parsed experience list (for gap penalty).

        Returns:
            Float in [0.0, 1.0].
        """
        education = education or []
        experience = experience or []

        base_score = self._years_ratio_score(candidate_years, required_years, job_title)
        edu_bonus  = self._education_bonus(education)
        gap_penalty = self._gap_penalty(experience)

        final = base_score + edu_bonus - gap_penalty
        return round(min(1.0, max(0.0, final)), 4)

    # ── Component scorers ─────────────────────────────────────────────────────

    def _years_ratio_score(
        self,
        candidate_years: float,
        required_years: float,
        job_title: str,
    ) -> float:
        """
        Base score from years ratio.

        Special cases:
          - required_years == 0 and candidate_years == 0: entry-level match → 0.5
          - required_years == 0 and candidate_years > 0: overqualified but fine → 0.9
        """
        if required_years <= 0:
            if candidate_years <= 0:
                return 0.5  # Both entry level — fair match
            return min(0.9, 0.5 + 0.1 * candidate_years)

        ratio = candidate_years / required_years
        ratio = min(ratio, self.overqualification_cap)

        # Linear: 0 years → 0, meets requirement → 0.9, overqualified cap → 1.0
        if ratio <= 0:
            base = 0.0
        elif ratio <= 1.0:
            base = 0.9 * ratio  # Proportional up to requirement
        else:
            # Overqualified — small bonus
            extra = (ratio - 1.0) / (self.overqualification_cap - 1.0)
            base = 0.9 + 0.1 * extra

        # Seniority mismatch penalty
        inferred_years = self._infer_years_from_title(job_title)
        if inferred_years and candidate_years < inferred_years * 0.5:
            # Significantly underqualified for the seniority level
            base *= 0.8

        return base

    def _education_bonus(self, education: list[dict]) -> float:
        """
        Small bonus for relevant higher education degrees.

        Master's/PhD: +0.08, Bachelor's: +0.05, otherwise: 0.
        """
        if not education:
            return 0.0
        for entry in education:
            degree_text = entry.get("degree", "").lower()
            if re.search(r"(phd|doctor|master|mba|m\.sc|m\.eng)", degree_text):
                return self.edu_bonus_max
            if _DEGREE_RE.search(degree_text):
                return self.edu_bonus_max * 0.6
        return 0.0

    def _gap_penalty(self, experience: list[dict]) -> float:
        """
        Penalty if there is a significant recent career gap.

        Currently a simple heuristic: looks for 'present' or 'current' in the
        most recent entry.  If not found, applies a small penalty.
        """
        if not experience:
            return 0.0
        most_recent = experience[0].get("date_range", "").lower()
        if re.search(r"(present|current|now|today)", most_recent):
            return 0.0  # Actively employed — no penalty
        # Could not confirm active employment — small penalty
        return self.gap_penalty_max * 0.5

    @staticmethod
    def _infer_years_from_title(job_title: str) -> float | None:
        """
        Return expected minimum years for a job title's seniority level.

        Returns None if seniority cannot be inferred.
        """
        if not job_title:
            return None
        if _LEAD_TITLE_RE.search(job_title):
            return 8.0
        if _SENIOR_TITLE_RE.search(job_title):
            return 5.0
        if _MID_TITLE_RE.search(job_title):
            return 3.0
        if _JUNIOR_TITLE_RE.search(job_title):
            return 0.0
        return None