"""
app/services/resume_analysis_service.py

High-level resume analysis service.

Changes vs previous version:
  - analyse() with force_reparse=True no longer calls parser.parse(file_path).
    That code path assumed a local file path, which breaks on Render
    (ephemeral filesystem) and with Cloudinary URLs.

  - The route (resumes.py:analyze_resume) now handles force_reparse itself:
      1. Downloads bytes from StorageService
      2. Calls parser.parse_bytes()
      3. Applies parse result to the Resume ORM object
      4. Calls analyse(resume, force_reparse=False) — data already fresh

  - This service only runs analysis on already-parsed data on the ORM
    object. It never touches the filesystem or network.

  - Everything else (section quality, Groq, persist, fallback) is identical.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Output of a resume analysis operation."""
    resume_id:        str = ""
    summary:          str = ""
    strengths:        list = field(default_factory=list)
    issues:           list = field(default_factory=list)
    role_suggestions: list = field(default_factory=list)
    improvement_tips: list = field(default_factory=list)
    section_quality:  float = 0.0
    llm_enhanced:     bool = False
    parse_error:      Optional[str] = None


# Rule-based fallback role mapping (skill → roles)
_SKILL_TO_ROLES = {
    "python":     [("Python Developer", 0.85), ("Data Engineer", 0.75), ("Backend Engineer", 0.80)],
    "react":      [("Frontend Developer", 0.85), ("Full Stack Developer", 0.80)],
    "java":       [("Java Developer", 0.85), ("Backend Engineer", 0.78)],
    "sql":        [("Data Analyst", 0.80), ("Database Administrator", 0.75)],
    "tensorflow": [("Machine Learning Engineer", 0.88), ("Data Scientist", 0.85)],
    "aws":        [("Cloud Engineer", 0.85), ("DevOps Engineer", 0.80)],
    "docker":     [("DevOps Engineer", 0.82), ("Platform Engineer", 0.78)],
    "kubernetes": [("Platform Engineer", 0.85), ("Site Reliability Engineer", 0.82)],
}


class ResumeAnalysisService:
    """
    Orchestrates resume analysis (section quality + LLM).

    This service does NOT handle file I/O or re-parsing.
    The route is responsible for downloading and re-parsing the file
    before calling analyse() — see resumes.py:analyze_resume().
    """

    def __init__(
        self,
        parser,
        section_quality_scorer,
        groq_service,
        resume_repo,
    ):
        self._parser = parser
        self._sq     = section_quality_scorer
        self._groq   = groq_service
        self._repo   = resume_repo

    def analyse(
        self,
        resume,
        force_reparse: bool = False,
        use_llm: bool = True,
    ) -> AnalysisResult:
        """
        Run analysis on a Resume ORM object whose parsed data is already present.

        IMPORTANT: force_reparse=True is a legacy parameter that previously
        called parser.parse(resume.file_path). That path is now handled by
        the route before calling this method. If force_reparse=True is passed
        here, it is silently treated as False — the data on the ORM object
        is used as-is. The route is responsible for refreshing it first.

        Args:
            resume:        Resume ORM instance with skills_list, experience_list etc.
            force_reparse: Ignored — kept for signature compatibility.
            use_llm:       Whether to call GroqService for enhanced analysis.

        Returns:
            AnalysisResult — always returns, never raises.
        """
        from app.models.enums import ParseStatus

        try:
            # ── Guard: must be parsed before analysis ──────────────────────────
            parse_status_val = getattr(
                getattr(resume, "parse_status", None), "value",
                str(getattr(resume, "parse_status", ""))
            )
            if parse_status_val != ParseStatus.SUCCESS.value:
                return AnalysisResult(
                    resume_id=resume.id,
                    parse_error=(
                        f"Resume parse status is '{parse_status_val}'. "
                        "Re-upload or re-parse before running analysis."
                    ),
                )

            # ── Section quality ────────────────────────────────────────────────
            sq_score = self._sq.score(
                skills=resume.skills_list,
                experience=resume.experience_list,
                education=resume.education_list,
                summary_text=resume.summary_text or "",
                certifications=resume.certifications_list,
                projects=resume.projects_list,
                raw_text_length=len(resume.raw_text or ""),
            )

            sq_missing = self._sq.get_missing_sections(
                skills=resume.skills_list,
                experience=resume.experience_list,
                education=resume.education_list,
                summary_text=resume.summary_text or "",
                certifications=resume.certifications_list,
                projects=resume.projects_list,
                raw_text_length=len(resume.raw_text or ""),
            )

            # ── LLM analysis ───────────────────────────────────────────────────
            llm_enhanced = False
            if use_llm and self._groq and self._groq.available:
                llm_data = self._groq.analyse_resume(
                    raw_text=resume.raw_text or "",
                    skills=resume.skills_list,
                    experience_years=resume.total_experience_years,
                    education=resume.education_list,
                )
                summary          = llm_data.get("summary", "")
                strengths        = llm_data.get("strengths", [])
                issues           = llm_data.get("issues", [])
                role_suggestions = llm_data.get("role_suggestions", [])
                improvement_tips = llm_data.get("improvement_tips", [])
                llm_enhanced     = True
            else:
                summary, strengths, issues, role_suggestions, improvement_tips = (
                    self._rule_based_analysis(resume, sq_score, sq_missing)
                )

            # ── Persist analysis fields ────────────────────────────────────────
            resume.resume_summary        = summary
            resume.issues_list           = issues
            resume.role_suggestions_list = role_suggestions
            resume.improvement_tips_list = improvement_tips
            self._repo.save(resume)

            return AnalysisResult(
                resume_id=resume.id,
                summary=summary,
                strengths=strengths,
                issues=issues,
                role_suggestions=role_suggestions,
                improvement_tips=improvement_tips,
                section_quality=sq_score,
                llm_enhanced=llm_enhanced,
            )

        except Exception as exc:
            logger.exception("Resume analysis failed for %s", resume.id)
            return AnalysisResult(resume_id=resume.id, parse_error=str(exc))

    # ─────────────────────────────────────────────────────────────────────────
    # Rule-based fallback
    # ─────────────────────────────────────────────────────────────────────────

    def _rule_based_analysis(
        self,
        resume,
        sq_score: float,
        missing_sections,
    ) -> tuple[str, list, list, list, list]:
        """Produce analysis results without calling the LLM."""
        skills           = resume.skills_list
        experience_years = resume.total_experience_years

        summary = (
            f"Candidate has {experience_years:.1f} years of experience "
            f"with expertise in {', '.join(skills[:5]) if skills else 'unknown areas'}."
        )

        strengths = []
        if experience_years >= 5:
            strengths.append(
                f"Strong {experience_years:.0f} years of professional experience"
            )
        if len(skills) >= 10:
            strengths.append(
                f"Broad technical skill set ({len(skills)} skills detected)"
            )

        issues = []
        if missing_sections:
            issues.append({
                "type":        "missing_section",
                "description": f"Resume is missing sections: {', '.join(missing_sections)}",
                "severity":    "medium",
            })

        # Role suggestions via skill mapping
        role_scores: dict[str, float] = {}
        for skill in skills:
            for role, score in _SKILL_TO_ROLES.get(skill.lower(), []):
                if role not in role_scores or role_scores[role] < score:
                    role_scores[role] = score

        role_suggestions_raw = [
            {
                "title":       role,
                "match_score": score,
                "reason":      f"Strong match based on {skill} skills",
            }
            for skill, roles in _SKILL_TO_ROLES.items()
            if skill in {s.lower() for s in skills}
            for role, score in roles
        ]
        seen: set[str] = set()
        role_suggestions = []
        for r in sorted(role_suggestions_raw, key=lambda x: -x["match_score"]):
            if r["title"] not in seen:
                seen.add(r["title"])
                role_suggestions.append(r)
        role_suggestions = role_suggestions[:5]

        improvement_tips = []
        oov = getattr(resume, "oov_skills_list", []) or []
        if len(skills) + len(oov) < 5:
            improvement_tips.append({
                "category": "skills",
                "tip":      "Add more technical skills to improve job match visibility.",
            })
        if oov:
            improvement_tips.append({
                "category": "skills",
                "tip": (
                    f"Resume mentions {len(oov)} unrecognised skill(s): "
                    f"{', '.join(oov[:5])}. Verify spelling or use standard names."
                ),
            })

        return summary, strengths, issues, role_suggestions, improvement_tips