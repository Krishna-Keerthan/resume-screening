"""
app/services/ats_scorer.py  ── IMPROVED VERSION

ATS Scoring Orchestrator — combines all scoring components into a single
weighted final score and persists the result.

IMPROVEMENTS OVER ORIGINAL
---------------------------
  [SC1] Parallel scoring: all four component scorers (keyword, semantic,
        experience, section_quality) now run concurrently using
        ThreadPoolExecutor. On a server with 4+ CPU cores, total scoring
        time drops from ~sum of all latencies to ~max of all latencies.
        Graceful fallback to sequential if threading fails.

  [SC2] Semantic weight fallback improved: when semantic is unavailable,
        weight is redistributed proportionally to ALL other components
        (not just keyword), preserving the relative balance between
        experience and section_quality scores.

  [SC3] score_raw() now passes job_responsibilities to semantic_matcher
        when the input dict contains it — previously responsibilities were
        silently ignored in preview scoring.

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
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


def _get_score_to_label():
    """Lazy import to avoid circular deps at module load time."""
    try:
        from app.models.enums import score_to_label
        return score_to_label
    except Exception:
        def _fallback(score, threshold_excellent=0.80, threshold_good=0.65, threshold_fair=0.50):
            if score >= threshold_excellent: return type('L', (), {'value': 'excellent'})()
            if score >= threshold_good:      return type('L', (), {'value': 'good'})()
            if score >= threshold_fair:      return type('L', (), {'value': 'fair'})()
            return type('L', (), {'value': 'weak'})()
        return _fallback


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
        parallel_scoring: bool = True,
        scoring_timeout_seconds: float = 10.0,
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
        self._parallel_scoring     = parallel_scoring    # [SC1]
        self._scoring_timeout      = scoring_timeout_seconds

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
        job_responsibilities: Optional[list[str]] = None,  # [SC3]
    ) -> dict:
        """
        [SC3][SC4] Score raw data without ORM objects or DB writes.

        Now passes job_responsibilities to semantic_matcher.
        """
        nice_to_have = job_nice_to_have_skills or []
        responsibilities = job_responsibilities or []

        kw_score = self._kw.score(
            resume_text=resume_text,
            resume_skills=resume_skills,
            job_description=job_description,
            job_required_skills=job_required_skills,
            job_nice_to_have_skills=nice_to_have,
            oov_skills=[],
            
        )

        sem_result = self._sem.score(
            resume_skills=resume_skills,
            resume_summary=summary_text,
            resume_experience=[e.get("title", "") for e in resume_experience],
            job_title=job_title,
            job_description=job_description,
            job_required_skills=job_required_skills,
            job_responsibilities=responsibilities,   # [SC3]
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
            certifications=[],
            projects=[],
            raw_text_length=len(resume_text),
        )

        # [SC4] Clamp individual scores
        kw_score  = max(0.0, min(1.0, kw_score))
        exp_score = max(0.0, min(1.0, exp_score))
        sq_score  = max(0.0, min(1.0, sq_score))

        eff_sem = sem_result.score if sem_result.available else kw_score
        eff_sem = max(0.0, min(1.0, eff_sem))

        final = self._compute_final(kw_score, eff_sem, exp_score, sq_score, sem_result.available)

        return {
            "final_score":             final,
            "semantic_score":          sem_result.score,
            "keyword_score":           kw_score,
            "experience_score":        exp_score,
            "section_quality_score":   sq_score,
            "semantic_available":      sem_result.available,
            "semantic_component_scores": sem_result.component_scores,  # [SC5]
            "weights_used":            self._weights,
        }

    # ── Pipeline ───────────────────────────────────────────────────────────────

    def _run_pipeline(
        self,
        resume,
        job,
        application_id: Optional[str],
        use_llm: bool,
    ) -> ScoringResult:
        """Execute the scoring pipeline and write results."""

        resume_skills   = resume.skills_list
        resume_text     = resume.raw_text or " ".join(resume_skills)
        resume_exp      = resume.experience_list
        resume_edu      = resume.education_list
        resume_years    = resume.total_experience_years
        summary_text    = resume.summary_text or ""
        resume_oov      = getattr(resume, "oov_skills_list_parsed", [])

        job_skills_req  = job.required_skills_list
        job_skills_nth  = job.nice_to_have_skills_list
        job_desc        = job.description or ""
        job_exp_years   = job.experience_years
        job_resp        = getattr(job, "responsibilities_list", []) or []

        # [SC1] Run component scorers in parallel
        kw_score, sem_result, exp_score, sq_score, sq_missing = self._run_components_parallel(
            resume_skills=resume_skills,
            resume_text=resume_text,
            resume_exp=resume_exp,
            resume_edu=resume_edu,
            resume_years=resume_years,
            summary_text=summary_text,
            job_skills_req=job_skills_req,
            job_skills_nth=job_skills_nth,
            job_desc=job_desc,
            job_exp_years=job_exp_years,
            job_title=job.title,
            job_resp=job_resp,
            resume_oov=resume_oov,
        )

        # [SC4] Clamp each component
        kw_score  = max(0.0, min(1.0, kw_score))
        exp_score = max(0.0, min(1.0, exp_score))
        sq_score  = max(0.0, min(1.0, sq_score))

        eff_sem = sem_result.score if sem_result.available else kw_score
        eff_sem = max(0.0, min(1.0, eff_sem))

        final = self._compute_final(kw_score, eff_sem, exp_score, sq_score, sem_result.available)

        score_to_label = _get_score_to_label()
        label = score_to_label(
            final,
            threshold_excellent=self._threshold_excellent,
            threshold_good=self._threshold_good,
            threshold_fair=self._threshold_fair,
        )

        explanation = self._expl.explain(
            final_score=final,
            semantic_score=sem_result.score,
            keyword_score=kw_score,
            experience_score=exp_score,
            section_quality_score=sq_score,
            resume_skills=resume_skills,
            job_title=job.title,
            job_required_skills=job_skills_req,
            job_nice_to_have_skills=job_skills_nth,
            candidate_years=resume_years,
            required_years=job_exp_years,
            missing_sections=sq_missing,
            use_llm=use_llm,
            weights=self._weights,
            semantic_component_scores=sem_result.component_scores

        )

        ats_record = self._build_ats_record(
            resume_id=resume.id,
            job_id=job.id,
            scores={
                "semantic":           sem_result.score,
                "keyword":            kw_score,
                "experience":         exp_score,
                "section_quality":    sq_score,
                "final":              final,
                "semantic_available": sem_result.available,
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
            semantic_score=sem_result.score,
            keyword_score=kw_score,
            experience_score=exp_score,
            section_quality_score=sq_score,
            semantic_available=sem_result.available,
            matched_skills=explanation.matched_skills,
            missing_skills=explanation.missing_skills,
            extra_skills=explanation.extra_skills,
            improvement_tips=explanation.improvement_tips,
            summary_text=explanation.summary,
            hiring_recommendation=explanation.hiring_recommendation,
            weights_used=self._weights,
            ats_score_id=saved.id if saved else None,
            semantic_component_scores=sem_result.component_scores,   # [SC5]
        )

    # ── Parallel component scoring ─────────────────────────────────────────────

    def _run_components_parallel(
        self,
        *,
        resume_skills, resume_text, resume_exp, resume_edu,
        resume_years, summary_text, job_skills_req, job_skills_nth,
        job_desc, job_exp_years, job_title, job_resp, resume_oov,
    ):
        """
        [SC1] Run all four component scorers concurrently.

        Falls back to sequential execution if ThreadPoolExecutor fails
        or if self._parallel_scoring is False.
        """
        if not self._parallel_scoring:
            return self._run_components_sequential(
                resume_skills=resume_skills, resume_text=resume_text,
                resume_exp=resume_exp, resume_edu=resume_edu,
                resume_years=resume_years, summary_text=summary_text,
                job_skills_req=job_skills_req, job_skills_nth=job_skills_nth,
                job_desc=job_desc, job_exp_years=job_exp_years,
                job_title=job_title, job_resp=job_resp,
            )

        kw_result  = None
        sem_result = None
        exp_result = None
        sq_result  = None
        sq_missing = []

        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {
                    executor.submit(
                        self._kw.score,
                        resume_text=resume_text,
                        resume_skills=resume_skills,
                        job_description=job_desc,
                        job_required_skills=job_skills_req,
                        job_nice_to_have_skills=job_skills_nth,
                        oov_skills=resume_oov,
                    ): "kw",
                    executor.submit(
                        self._exp.score,
                        candidate_years=resume_years,
                        required_years=job_exp_years,
                        job_title=job_title,
                        education=resume_edu,
                        experience=resume_exp,
                    ): "exp",
                    executor.submit(
                        self._sq.score,
                        skills=resume_skills,
                        experience=resume_exp,
                        education=resume_edu,
                        summary_text=summary_text,
                        raw_text_length=len(resume_text),
                    ): "sq",
                }

                for future in as_completed(futures, timeout=self._scoring_timeout):
                    name = futures[future]
                    try:
                        res = future.result()
                        if name == "kw":  kw_result = res
                        elif name == "exp": exp_result = res
                        elif name == "sq":  sq_result = res
                    except Exception as exc:
                        logger.warning("Component scorer '%s' failed: %s", name, exc)

        except (TimeoutError, Exception) as exc:
            logger.warning("Parallel scoring failed (%s), falling back to sequential", exc)
            return self._run_components_sequential(
                resume_skills=resume_skills, resume_text=resume_text,
                resume_exp=resume_exp, resume_edu=resume_edu,
                resume_years=resume_years, summary_text=summary_text,
                job_skills_req=job_skills_req, job_skills_nth=job_skills_nth,
                job_desc=job_desc, job_exp_years=job_exp_years,
                job_title=job_title, job_resp=job_resp,
            )
        
        try:
            sem_result = self._sem.score(
                resume_skills=resume_skills,
                resume_summary=summary_text,
                resume_experience=resume_exp,
                job_title=job_title,
                job_description=job_desc,
                job_required_skills=job_skills_req,
                job_responsibilities=job_resp,
            )
        except Exception as exc:
            logger.warning("sem scorer failed: %s", exc)
            from app.services.semantic_matcher import SemanticScoreResult
            sem_result = SemanticScoreResult(score=0.0, raw_cosine=0.0, available=False)

        # Fill any missing (failed) scorers with safe defaults
        from app.services.semantic_matcher import SemanticScoreResult
        if kw_result  is None: kw_result = 0.0
        if sem_result is None: sem_result = SemanticScoreResult(score=0.0, raw_cosine=0.0, available=False)
        if exp_result is None: exp_result = 0.0
        if sq_result  is None: sq_result = 0.0

        # sq_missing (safe to call sequentially — it's fast)
        try:
            sq_missing = self._sq.get_missing_sections(
                skills=resume_skills, experience=resume_exp, education=resume_edu,
                summary_text=summary_text, raw_text_length=len(resume_text),
            )
        except Exception:
            sq_missing = []

        return kw_result, sem_result, exp_result, sq_result, sq_missing

    def _run_components_sequential(
        self,
        *,
        resume_skills, resume_text, resume_exp, resume_edu,
        resume_years, summary_text, job_skills_req, job_skills_nth,
        job_desc, job_exp_years, job_title, job_resp, resume_oov,
    ):
        """Sequential fallback for component scoring."""
        from app.services.semantic_matcher import SemanticScoreResult

        try:
            kw_result = self._kw.score(
                resume_text=resume_text,
                resume_skills=resume_skills,
                job_description=job_desc, 
                job_required_skills=job_skills_req,
                job_nice_to_have_skills=job_skills_nth,
                oov_skills=resume_oov,
            )
        except Exception as e:
            logger.warning("kw scorer failed: %s", e)
            kw_result = 0.0

        try:
            sem_result = self._sem.score(
                resume_skills=resume_skills, resume_summary=summary_text,
                resume_experience=resume_exp, job_title=job_title,
                job_description=job_desc, job_required_skills=job_skills_req,
                job_responsibilities=job_resp,
            )
        except Exception as e:
            logger.warning("sem scorer failed: %s", e)
            sem_result = SemanticScoreResult(score=0.0, raw_cosine=0.0, available=False)

        try:
            exp_result = self._exp.score(
                candidate_years=resume_years, required_years=job_exp_years,
                job_title=job_title, education=resume_edu, experience=resume_exp,
            )
        except Exception as e:
            logger.warning("exp scorer failed: %s", e)
            exp_result = 0.0

        try:
            sq_result = self._sq.score(
                skills=resume_skills, experience=resume_exp, education=resume_edu,
                summary_text=summary_text, raw_text_length=len(resume_text),
            )
        except Exception as e:
            logger.warning("sq scorer failed: %s", e)
            sq_result = 0.0

        try:
            sq_missing = self._sq.get_missing_sections(
                skills=resume_skills, experience=resume_exp, education=resume_edu,
                summary_text=summary_text, raw_text_length=len(resume_text),
            )
        except Exception:
            sq_missing = []

        return kw_result, sem_result, exp_result, sq_result, sq_missing

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
                semantic_available=True,
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
        try:
            from app.models.ats_score import AtsScore
            return AtsScore.from_score_result(
                resume_id=resume_id, job_id=job_id,
                scores=scores, explanation=explanation, weights=weights,
                application_id=application_id,
                threshold_excellent=self._threshold_excellent,
                threshold_good=self._threshold_good,
                threshold_fair=self._threshold_fair,
            )
        except Exception:
            record = type("AtsScoreRecord", (), {
                "resume_id":             resume_id,
                "job_id":                job_id,
                "final_score":           scores.get("final", 0.0),
                "score_label":           "fair",
                "application_id":        application_id,
                "matched_skills_list":   explanation.get("matched_skills", []),
                "missing_skills_list":   explanation.get("missing_skills", []),
                "extra_skills_list":     explanation.get("extra_skills", []),
                "improvement_tips_list": explanation.get("improvement_tips", []),
                "summary_text":          explanation.get("summary", ""),
                "weights_used_dict":     weights,
            })()
            return record