"""
app/services/section_quality_scorer.py

Resume section quality scorer.

Evaluates how complete and well-structured a resume is.  This score rewards
candidates who have provided rich, parseable resumes and penalises sparse
or unstructured uploads.

Scoring components (weights in parentheses):
  - Has skills section with ≥ 5 skills          (0.25)
  - Has experience section with ≥ 1 entry       (0.25)
  - Has education section with ≥ 1 entry        (0.15)
  - Has summary/objective                        (0.10)
  - Has certifications                           (0.10)
  - Has projects section                         (0.10)
  - Raw text length >= 300 chars                 (0.05)

Final score = weighted sum of satisfied criteria, clamped to [0.0, 1.0].

Design:
  - Deterministic: same resume always gets the same score.
  - Transparent: every penalty/bonus is itemised in get_breakdown().
  - No ML required.

Usage:
    from app.services.section_quality_scorer import SectionQualityScorerService
    svc = SectionQualityScorerService()
    score = svc.score(
        skills=["python", "flask", "react"],
        experience=[{"title": "Engineer", "company": "Acme"}],
        education=[{"degree": "BSc CS", "institution": "MIT"}],
        summary_text="Experienced backend developer...",
        certifications=["AWS SAA"],
        projects=[{"name": "Open Source Tool"}],
        raw_text_length=2400,
    )
"""

import logging

logger = logging.getLogger(__name__)


class SectionQualityScorerService:
    """
    Deterministic resume completeness / quality scorer.

    Criteria and weights are class-level constants — easy to audit.
    """

    _CRITERIA = [
        # (name, weight)
        ("has_skills",          0.25),
        ("has_experience",      0.25),
        ("has_education",       0.15),
        ("has_summary",         0.10),
        ("has_certifications",  0.10),
        ("has_projects",        0.10),
        ("sufficient_length",   0.05),
    ]

    # Minimum counts to satisfy each criterion
    _MIN_SKILLS       = 3
    _MIN_EXPERIENCE   = 1
    _MIN_EDUCATION    = 1
    _MIN_TEXT_LENGTH  = 300

    def score(
        self,
        skills: list[str],
        experience: list[dict],
        education: list[dict],
        summary_text: str = "",
        certifications: list[str] | None = None,
        projects: list[dict] | None = None,
        raw_text_length: int = 0,
    ) -> float:
        """
        Compute section quality score.

        Args:
            skills:           Extracted skills list.
            experience:       Extracted experience entries.
            education:        Extracted education entries.
            summary_text:     Summary/objective text.
            certifications:   Extracted certifications.
            projects:         Extracted project entries.
            raw_text_length:  Length of raw_text in characters.

        Returns:
            Float in [0.0, 1.0].
        """
        breakdown = self.get_breakdown(
            skills=skills,
            experience=experience,
            education=education,
            summary_text=summary_text,
            certifications=certifications or [],
            projects=projects or [],
            raw_text_length=raw_text_length,
        )
        total = sum(w for _, (satisfied, w) in breakdown.items() if satisfied)
        return round(min(1.0, max(0.0, total)), 4)

    def get_breakdown(
        self,
        skills: list[str],
        experience: list[dict],
        education: list[dict],
        summary_text: str = "",
        certifications: list[str] | None = None,
        projects: list[dict] | None = None,
        raw_text_length: int = 0,
    ) -> dict[str, tuple[bool, float]]:
        """
        Return itemised criterion → (satisfied, weight) dict.

        Useful for generating improvement tips ("Add a skills section").
        """
        certifications = certifications or []
        projects = projects or []

        return {
            "has_skills":         (len(skills) >= self._MIN_SKILLS,       0.25),
            "has_experience":     (len(experience) >= self._MIN_EXPERIENCE, 0.25),
            "has_education":      (len(education) >= self._MIN_EDUCATION,  0.15),
            "has_summary":        (bool(summary_text and len(summary_text) > 20), 0.10),
            "has_certifications": (len(certifications) >= 1,              0.10),
            "has_projects":       (len(projects) >= 1,                    0.10),
            "sufficient_length":  (raw_text_length >= self._MIN_TEXT_LENGTH, 0.05),
        }

    def get_missing_sections(
        self,
        skills: list[str],
        experience: list[dict],
        education: list[dict],
        summary_text: str = "",
        certifications: list[str] | None = None,
        projects: list[dict] | None = None,
        raw_text_length: int = 0,
    ) -> list[str]:
        """
        Return list of unsatisfied criterion names.

        Used by ExplainabilityEngine to generate targeted improvement tips.
        """
        breakdown = self.get_breakdown(
            skills=skills, experience=experience, education=education,
            summary_text=summary_text, certifications=certifications or [],
            projects=projects or [], raw_text_length=raw_text_length,
        )
        return [name for name, (satisfied, _) in breakdown.items() if not satisfied]