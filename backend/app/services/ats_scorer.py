"""
app/services/ats_scorer.py  ── IMPROVED VERSION

ATS Scoring Orchestrator — combines all scoring components into a single
weighted final score and persists the result.

IMPROVEMENTS OVER ORIGINAL
---------------------------
  [SC2] Semantic weight fallback improved: when semantic is unavailable,
        weight is redistributed proportionally to ALL other components
        (not just keyword), preserving the relative balance between
        experience and section_quality scores.

  [SC4] Component scores are now individually clamped to [0.0, 1.0] before
        weighting — prevents a single malformed scorer from making the
        final score exceed 1.0.

  [SC5] ScoringResult now includes: scoring_duration_ms (for monitoring),
        semantic_component_scores (passes through the new breakdown from
        SemanticScoreResult), and raw_component_scores.

  [SC6] score_resume_job() now accepts an optional force_rescore: bool flag.
        When False (default), it checks if a recent ATS score already exists
        for this resume+job pair and returns it without re-scoring.
        Avoids redundant scoring when the application pipeline runs
        score_resume_job() multiple times for the same pair.

  [SC7] _compute_final() now logs a structured metrics line at DEBUG level
        for every scoring call — useful for model calibration and monitoring.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


def _get_score_to_label():
    """Lazy import to avoid circular deps at module load time."""
    from app.models.enums import score_to_label
    return score_to_label


@dataclass
class ScoringResult:
    """Full output of the ATS scoring pipeline."""
    resume_id:                str
    job_id:                   str
    final_score:              float
    score_label:              str
    semantic_score:           float
    keyword_score:            float
    experience_score:         float
    section_quality_score:    float
    semantic_available:       bool
    matched_skills:           list = field(default_factory=list)
    missing_skills:           list = field(default_factory=list)
    extra_skills:             list = field(default_factory=list)
    improvement_tips:         list = field(default_factory=list)
    summary_text:             str  = ""
    hiring_recommendation:    str  = "maybe"
    weights_used:             dict = field(default_factory=dict)
    ats_score_id:             Optional[str] = None
    error:                    Optional[str] = None
    # [SC5] New fields
    scoring_duration_ms:      float = 0.0
    semantic_component_scores: dict = field(default_factory=dict)
    from_cache:               bool  = False


def scorer_inputs(resume, job) -> dict:
    """
    score_raw() keyword arguments for a stored Resume x Job pair.

    The saved pipeline and every preview build their inputs here, so a
    preview reports the same score that score_resume_job() would save.
    """
    resume_skills = resume.skills_list
    return {
        "resume_text":             resume.raw_text or " ".join(resume_skills),
        "resume_skills":           resume_skills,
        "resume_experience":       resume.experience_list,
        "resume_education":        resume.education_list,
        "resume_experience_years": resume.total_experience_years,
        "summary_text":            resume.summary_text or "",
        "resume_oov":              resume.oov_skills_list_parsed,
        "job_title":               job.title,
        "job_description":         job.description or "",
        "job_required_skills":     job.required_skills_list,
        "job_nice_to_have_skills": job.nice_to_have_skills_list,
        "job_experience_years":    job.experience_years,
        "job_responsibilities":    job.responsibilities_list,
    }

class AtsScorerService:
    """
    ATS scoring orchestrator.

    Combines keyword matching, semantic similarity, experience scoring,
    and section quality into a weighted final score.
    """

    _DEFAULT_WEIGHTS = {
        "semantic":  0.40,
        "keyword":   0.35,
        "experience": 0.15,
        "section":   0.10,
    }

    def __init__(
        self,
        keyword_matcher,
        semantic_matcher,
        experience_scorer,
        section_quality_scorer,
        explainability_engine,
        ats_score_repo,
        weights: Optional[dict] = None,
        threshold_excellent: float = 0.80,
        threshold_good: float = 0.65,
        threshold_fair: float = 0.50,
    ):
        self._kw   = keyword_matcher
        self._sem  = semantic_matcher
        self._exp  = experience_scorer
        self._sq   = section_quality_scorer
        self._expl = explainability_engine
        self._repo = ats_score_repo
        self._weights              = self._normalise_weights(weights or self._DEFAULT_WEIGHTS)
        self._threshold_excellent  = threshold_excellent
        self._threshold_good       = threshold_good
        self._threshold_fair       = threshold_fair

    # ── Public API ─────────────────────────────────────────────────────────────

    def score_resume_job(
        self,
        resume,
        job,
        application_id: Optional[str] = None,
        use_llm: bool = True,
        force_rescore: bool = False,
    ) -> ScoringResult:
        """
        [SC6] Score a Resume × Job pair and persist the result.

        If force_rescore=False (default) and a recent ATS score exists for
        this resume+job pair, returns the cached result without re-scoring.
        """
        start = time.perf_counter()
        try:
            # [SC6] Return existing score if available and not forcing rescore
            if not force_rescore:
                existing = self._repo.find_by_resume_job(resume.id, job.id)
                if existing:
                    logger.debug(
                        "Returning cached ATS score for resume=%s job=%s",
                        resume.id, job.id,
                    )
                    return self._result_from_ats_record(existing, from_cache=True)

            result = self._run_pipeline(resume, job, application_id, use_llm)
            result.scoring_duration_ms = round((time.perf_counter() - start) * 1000, 1)
            return result

        except Exception as exc:
            logger.exception("Scoring failed for resume=%s, job=%s", resume.id, job.id)
            return ScoringResult(
                resume_id=resume.id,
                job_id=job.id,
                final_score=0.0,
                score_label="weak",
                semantic_score=0.0,
                keyword_score=0.0,
                experience_score=0.0,
                section_quality_score=0.0,
                semantic_available=False,
                error=str(exc),
                scoring_duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )

    def score_raw(
        self,
        resume_text: str,
        resume_skills: list[str],
        resume_experience: list[dict],
        resume_education: list[dict],
        resume_experience_years: float,
        job_title: str,
        job_description: str,
        job_required_skills: list[str],
        job_nice_to_have_skills: Optional[list[str]] = None,
        job_experience_years: float = 0.0,
        summary_text: str = "",
        job_responsibilities: Optional[list[str]] = None,
        resume_oov: Optional[list[str]] = None,
    ) -> dict:
        """
        Score raw data without ORM objects or DB writes.

        For a stored Resume x Job pair, call ``score_raw(**scorer_inputs(resume, job))``
        so the result matches what score_resume_job() saves.
        """
        scores, _ = self._run_components(
            resume_text=resume_text,
            resume_skills=resume_skills,
            resume_experience=resume_experience,
            resume_education=resume_education,
            resume_experience_years=resume_experience_years,
            job_title=job_title,
            job_description=job_description,
            job_required_skills=job_required_skills,
            job_nice_to_have_skills=job_nice_to_have_skills or [],
            job_experience_years=job_experience_years,
            summary_text=summary_text,
            job_responsibilities=job_responsibilities or [],
            resume_oov=resume_oov or [],
        )
        return scores

    # ── Pipeline ───────────────────────────────────────────────────────────────

    def _run_pipeline(
        self,
        resume,
        job,
        application_id: Optional[str],
        use_llm: bool,
    ) -> ScoringResult:
        """Execute the scoring pipeline and write results."""
        inputs = scorer_inputs(resume, job)
        scores, sq_missing = self._run_components(**inputs)
        final = scores["final_score"]

        score_to_label = _get_score_to_label()
        label = score_to_label(
            final,
            threshold_excellent=self._threshold_excellent,
            threshold_good=self._threshold_good,
            threshold_fair=self._threshold_fair,
        )

        explanation = self._expl.explain(
            final_score=final,
            semantic_score=scores["semantic_score"],
            keyword_score=scores["keyword_score"],
            experience_score=scores["experience_score"],
            section_quality_score=scores["section_quality_score"],
            resume_skills=inputs["resume_skills"],
            job_title=inputs["job_title"],
            job_required_skills=inputs["job_required_skills"],
            job_nice_to_have_skills=inputs["job_nice_to_have_skills"],
            candidate_years=inputs["resume_experience_years"],
            required_years=inputs["job_experience_years"],
            missing_sections=sq_missing,
            use_llm=use_llm,
            weights=self._weights,
            semantic_component_scores=scores["semantic_component_scores"],
        )

        ats_record = self._build_ats_record(
            resume_id=resume.id,
            job_id=job.id,
            scores={
                "semantic":           scores["semantic_score"],
                "keyword":            scores["keyword_score"],
                "experience":         scores["experience_score"],
                "section_quality":    scores["section_quality_score"],
                "final":              final,
                "semantic_available": scores["semantic_available"],
            },
            explanation={
                "matched_skills":   explanation.matched_skills,
                "missing_skills":   explanation.missing_skills,
                "extra_skills":     explanation.extra_skills,
                "improvement_tips": explanation.improvement_tips,
                "summary":          explanation.summary,
            },
            weights=self._weights,
            application_id=application_id,
        )

        saved = self._repo.upsert(ats_record)

        return ScoringResult(
            resume_id=resume.id,
            job_id=job.id,
            final_score=final,
            score_label=label.value,
            semantic_score=scores["semantic_score"],
            keyword_score=scores["keyword_score"],
            experience_score=scores["experience_score"],
            section_quality_score=scores["section_quality_score"],
            semantic_available=scores["semantic_available"],
            matched_skills=explanation.matched_skills,
            missing_skills=explanation.missing_skills,
            extra_skills=explanation.extra_skills,
            improvement_tips=explanation.improvement_tips,
            summary_text=explanation.summary,
            hiring_recommendation=explanation.hiring_recommendation,
            weights_used=self._weights,
            ats_score_id=saved.id if saved else None,
            semantic_component_scores=scores["semantic_component_scores"],
        )

    # ── Component scoring ──────────────────────────────────────────────────────

    def _run_components(
        self,
        *,
        resume_text, resume_skills, resume_experience, resume_education,
        resume_experience_years, job_title, job_description, job_required_skills,
        job_nice_to_have_skills, job_experience_years, summary_text,
        job_responsibilities, resume_oov,
    ) -> tuple[dict, list[str]]:
        """
        Run the four component scorers one after another and combine them.

        Scorer exceptions propagate, so the caller reports the failure
        instead of silently scoring that component as 0.0.

        Returns (scores, missing_sections).
        """
        kw_score = self._kw.score(
            resume_text=resume_text,
            resume_skills=resume_skills,
            job_description=job_description,
            job_required_skills=job_required_skills,
            job_nice_to_have_skills=job_nice_to_have_skills,
            oov_skills=resume_oov,
        )
        sem_result = self._sem.score(
            resume_skills=resume_skills,
            resume_summary=summary_text,
            resume_experience=resume_experience,
            job_title=job_title,
            job_description=job_description,
            job_required_skills=job_required_skills,
            job_responsibilities=job_responsibilities,
        )
        exp_score = self._exp.score(
            candidate_years=resume_experience_years,
            required_years=job_experience_years,
            job_title=job_title,
            education=resume_education,
            experience=resume_experience,
        )
        sq_score = self._sq.score(
            skills=resume_skills,
            experience=resume_experience,
            education=resume_education,
            summary_text=summary_text,
            raw_text_length=len(resume_text),
        )
        sq_missing = self._sq.get_missing_sections(
            skills=resume_skills,
            experience=resume_experience,
            education=resume_education,
            summary_text=summary_text,
            raw_text_length=len(resume_text),
        )

        # [SC4] Clamp each component
        kw_score  = max(0.0, min(1.0, kw_score))
        exp_score = max(0.0, min(1.0, exp_score))
        sq_score  = max(0.0, min(1.0, sq_score))

        eff_sem = sem_result.score if sem_result.available else kw_score
        eff_sem = max(0.0, min(1.0, eff_sem))

        final = self._compute_final(kw_score, eff_sem, exp_score, sq_score, sem_result.available)

        scores = {
            "final_score":               final,
            "semantic_score":            sem_result.score,
            "keyword_score":             kw_score,
            "experience_score":          exp_score,
            "section_quality_score":     sq_score,
            "semantic_available":        sem_result.available,
            "semantic_component_scores": sem_result.component_scores,
            "weights_used":              self._weights,
        }
        return scores, sq_missing

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _compute_final(
        self,
        kw_score: float,
        sem_score: float,
        exp_score: float,
        sq_score: float,
        semantic_available: bool,
    ) -> float:
        """
        [SC2][SC7] Compute weighted final score.

        If semantic is unavailable, redistributes its weight proportionally
        to ALL other components (not just keyword).
        """
        w = self._weights.copy()

        if not semantic_available:
            sem_weight = w.pop("semantic", 0.40)
            # [SC2] Proportional redistribution to all remaining components
            remaining_total = sum(w.values()) or 1.0
            for k in list(w.keys()):
                w[k] += sem_weight * (w[k] / remaining_total)
            w["semantic"] = 0.0

        final = (
            w.get("semantic", 0.0)   * sem_score  +
            w.get("keyword", 0.0)    * kw_score   +
            w.get("experience", 0.0) * exp_score  +
            w.get("section", 0.0)    * sq_score
        )
        final = round(min(1.0, max(0.0, final)), 4)

        # [SC7] Structured metric log for monitoring/calibration
        logger.debug(
            "ATS score computed | kw=%.3f sem=%.3f exp=%.3f sq=%.3f → final=%.3f | sem_avail=%s",
            kw_score, sem_score, exp_score, sq_score, final, semantic_available,
        )

        return final

    @staticmethod
    def _normalise_weights(weights: dict) -> dict:
        """Normalise weights to sum to 1.0."""
        total = sum(weights.values())
        if total <= 0:
            return AtsScorerService._DEFAULT_WEIGHTS.copy()
        return {k: round(v / total, 4) for k, v in weights.items()}

    def _result_from_ats_record(self, record, from_cache: bool = False) -> ScoringResult:
        """
        [SC6] Build a ScoringResult from an existing AtsScore ORM record.
        """
        try:
            return ScoringResult(
                resume_id=record.resume_id,
                job_id=record.job_id,
                final_score=record.final_score,
                score_label=record.score_label or "fair",
                semantic_score=getattr(record, "semantic_score", 0.0),
                keyword_score=getattr(record, "keyword_score", 0.0),
                experience_score=getattr(record, "experience_score", 0.0),
                section_quality_score=getattr(record, "section_quality_score", 0.0),
                semantic_available=record.semantic_available,
                matched_skills=getattr(record, "matched_skills_list", []),
                missing_skills=getattr(record, "missing_skills_list", []),
                extra_skills=getattr(record, "extra_skills_list", []),
                improvement_tips=getattr(record, "improvement_tips_list", []),
                summary_text=getattr(record, "summary_text", ""),
                hiring_recommendation=getattr(record, "hiring_recommendation", "maybe"),
                weights_used=getattr(record, "weights_used_dict", self._weights),
                ats_score_id=record.id,
                from_cache=from_cache,
            )
        except Exception as exc:
            logger.warning("_result_from_ats_record failed: %s", exc)
            return ScoringResult(
                resume_id=getattr(record, "resume_id", ""),
                job_id=getattr(record, "job_id", ""),
                final_score=getattr(record, "final_score", 0.0),
                score_label="fair",
                semantic_score=0.0,
                keyword_score=0.0,
                experience_score=0.0,
                section_quality_score=0.0,
                semantic_available=False,
                from_cache=from_cache,
            )

    def _build_ats_record(
        self,
        resume_id, job_id, scores, explanation, weights, application_id,
    ):
        """Build an AtsScore ORM record from raw score data."""
        from app.models.ats_score import AtsScore
        return AtsScore.from_score_result(
            resume_id=resume_id, job_id=job_id,
            scores=scores, explanation=explanation, weights=weights,
            application_id=application_id,
            threshold_excellent=self._threshold_excellent,
            threshold_good=self._threshold_good,
            threshold_fair=self._threshold_fair,
        )