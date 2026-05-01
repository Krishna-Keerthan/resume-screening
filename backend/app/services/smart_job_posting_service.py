"""
app/services/smart_job_posting_service.py

Smart job posting service — enhances job postings using LLM and
job parser, then persists structured data to the Job record.

Pipeline:
  1. Parse raw description with JobParserService (extract skills, etc.)
  2. Call GroqService.enhance_job_posting() for LLM enhancement.
  3. Merge parser output with LLM output (LLM wins on prose, parser wins
     on structured fields when LLM output is empty).
  4. Persist enhanced fields on the Job ORM object.
  5. Return EnhancedJobResult.

Design:
  - LLM enhancement is optional — parser output is always used as fallback.
  - quality_score and completeness_score are computed and persisted so
    recruiters can see how well-written their postings are.
  - Duplicate detection: find_duplicates() checks for jobs with the same
    title+company combination (calls JobRepository).

Usage:
    from app.services.smart_job_posting_service import SmartJobPostingService

    svc = SmartJobPostingService(
        job_parser=parser_svc,
        groq_service=groq_svc,
        job_repo=job_repo,
    )

    result = svc.enhance(job=job_obj, use_llm=True)
    duplicates = svc.find_duplicates(title="Backend Engineer", company="Acme Corp", recruiter_id="abc")
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EnhancedJobResult:
    """Output of the job posting enhancement pipeline."""
    job_id:               str
    required_skills:      list = field(default_factory=list)
    nice_to_have_skills:  list = field(default_factory=list)
    responsibilities:     list = field(default_factory=list)
    enhanced_description: str = ""
    quality_score:        float = 0.5
    completeness_score:   float = 0.5
    suggestions:          list = field(default_factory=list)
    duplicate_ids:        list = field(default_factory=list)
    llm_enhanced:         bool = False


class SmartJobPostingService:
    """
    Enhances job postings with structured data and LLM-generated improvements.
    """

    def __init__(self, job_parser, groq_service, job_repo):
        self._parser = job_parser
        self._groq   = groq_service
        self._repo   = job_repo

    def enhance(
        self,
        job,
        use_llm: bool = True,
    ) -> EnhancedJobResult:
        """
        Enhance a Job ORM object with structured data and optional LLM content.

        Args:
            job:     Job ORM instance.
            use_llm: Whether to call GroqService for prose enhancement.

        Returns:
            EnhancedJobResult — always returns, never raises.
        """
        try:
            return self._run_pipeline(job, use_llm)
        except Exception as exc:
            logger.exception("Job enhancement failed for %s", job.id)
            return EnhancedJobResult(job_id=job.id)

    def find_duplicates(
        self,
        title: str,
        company: str,
        recruiter_id: str,
        exclude_job_id: Optional[str] = None,
    ) -> list[str]:
        """
        Find existing jobs with the same title and company.

        Returns:
            List of duplicate Job IDs (excluding exclude_job_id).
        """
        try:
            duplicates = self._repo.find_duplicates(
                title=title,
                company=company,
                recruiter_id=recruiter_id,
            )
            if exclude_job_id:
                duplicates = [j for j in duplicates if j.id != exclude_job_id]
            return [j.id for j in duplicates]
        except Exception as exc:
            logger.warning("Duplicate check failed: %s", exc)
            return []

    # ── Pipeline ──────────────────────────────────────────────────────────────

    def _run_pipeline(self, job, use_llm: bool) -> EnhancedJobResult:
        """Internal pipeline execution."""

        # ── 1. Parser (always runs) ───────────────────────────────────────────
        parse_result = self._parser.parse_job_dict({
            "title":       job.title,
            "description": job.description or "",
        })

        # Use parsed skills as baseline
        required_skills    = parse_result.required_skills or job.required_skills_list
        nice_to_have       = parse_result.nice_to_have_skills or job.nice_to_have_skills_list
        responsibilities   = parse_result.responsibilities or job.responsibilities_list
        quality_score      = self._compute_quality(job, parse_result)
        completeness_score = self._compute_completeness(job, required_skills, responsibilities)
        enhanced_desc      = job.description
        suggestions        = []
        llm_enhanced       = False

        # ── 2. LLM enhancement (optional) ────────────────────────────────────
        if use_llm and self._groq and self._groq.available:
            llm_data = self._groq.enhance_job_posting(
                title=job.title,
                description=job.description or "",
                required_skills=required_skills,
                experience_years=job.experience_years,
                location=job.location,
            )
            if llm_data:
                enhanced_desc   = llm_data.get("enhanced_description", enhanced_desc) or enhanced_desc
                llm_req         = llm_data.get("required_skills", [])
                llm_nth         = llm_data.get("nice_to_have_skills", [])
                llm_resp        = llm_data.get("responsibilities", [])
                # Merge: LLM skills + parsed skills (deduplicated)
                required_skills   = list(dict.fromkeys(llm_req + required_skills))[:20]
                nice_to_have      = list(dict.fromkeys(llm_nth + nice_to_have))[:10]
                responsibilities  = llm_resp if llm_resp else responsibilities
                quality_score     = float(llm_data.get("quality_score", quality_score))
                completeness_score = float(llm_data.get("completeness_score", completeness_score))
                suggestions       = llm_data.get("suggestions", [])
                llm_enhanced      = True

        # ── 3. Persist ────────────────────────────────────────────────────────
        job.required_skills_list      = required_skills
        job.nice_to_have_skills_list  = nice_to_have
        job.responsibilities_list     = responsibilities
        job.description               = enhanced_desc
        job.quality_score             = round(min(1.0, max(0.0, quality_score)), 3)
        job.completeness_score        = round(min(1.0, max(0.0, completeness_score)), 3)
        self._repo.save(job)

        return EnhancedJobResult(
            job_id=job.id,
            required_skills=required_skills,
            nice_to_have_skills=nice_to_have,
            responsibilities=responsibilities,
            enhanced_description=enhanced_desc,
            quality_score=job.quality_score,
            completeness_score=job.completeness_score,
            suggestions=suggestions,
            llm_enhanced=llm_enhanced,
        )

    # ── Score helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _compute_quality(job, parse_result) -> float:
        """
        Rule-based quality score (0–1) before LLM.

        Rewards: long description, salary range, skills extracted.
        """
        score = 0.0
        desc_len = len(job.description or "")
        if desc_len >= 500:   score += 0.30
        elif desc_len >= 200: score += 0.20
        elif desc_len >= 50:  score += 0.10
        if job.salary_min and job.salary_max:
            score += 0.20
        elif job.salary_min or job.salary_max:
            score += 0.10
        if parse_result.required_skills:
            score += 0.25
        if job.experience_years > 0:
            score += 0.10
        if job.location and job.location.lower() not in ("remote", ""):
            score += 0.05
        return min(1.0, score)

    @staticmethod
    def _compute_completeness(
        job,
        required_skills: list,
        responsibilities: list,
    ) -> float:
        """
        Completeness score based on which fields are populated.
        """
        score = 0.0
        checks = [
            (bool(job.title),          0.20),
            (bool(job.description),    0.20),
            (bool(required_skills),    0.20),
            (bool(responsibilities),   0.15),
            (bool(job.salary_min),     0.10),
            (job.experience_years > 0, 0.10),
            (bool(job.location),       0.05),
        ]
        for satisfied, weight in checks:
            if satisfied:
                score += weight
        return min(1.0, score)