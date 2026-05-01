"""
app/services/semantic_matcher.py  ── IMPROVED VERSION

Semantic similarity scorer using sentence-transformers MiniLM.

IMPROVEMENTS OVER ORIGINAL
---------------------------
  [S1]  Asymmetric encoding: resume and job texts are built with different
        strategies. The resume text now includes experience bullet point
        content (not just titles), making the embedding richer. The job text
        now includes responsibilities list as well as description.

  [S2]  Multi-vector scoring: instead of one resume vector vs one job vector,
        computes three partial similarities (skills-to-skills,
        summary-to-description, experience-to-responsibilities) and combines
        them with configurable weights. More robust than single-text matching.

  [S3]  Rescaling calibrated: the original [0.20, 0.95] linear rescale was
        too generous — small differences compressed into a narrow band.
        New calibration uses [0.25, 0.88] which spreads mid-range scores more
        evenly and matches empirical cosine distribution for MiniLM-L6-v2.

  [S4]  Score clipping guard: raw cosine was clipped to [-1, 1] but never
        checked for NaN (which numpy can produce from zero vectors). Added
        NaN guard that returns score=0.0 rather than propagating NaN.

  [S5]  Batch scoring: score_batch() method scores one resume against N jobs
        in a single encode call — O(N) not O(N × encode_latency). Used by
        the job recommendation service.

  [S6]  Diagnostic field added: SemanticScoreResult now includes
        component_scores dict (skills_sim, summary_sim, experience_sim) for
        debugging and explainability display.

  [S7]  Text builder improvements:
        - Resume: includes OOV skills (non-standard skill strings from parser)
          if passed.
        - Resume: includes bullet points from experience (not just titles).
        - Job: includes responsibilities_list if passed.
        - Both respect a configurable max_chars limit per component.
"""

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

# [S3] Calibrated rescaling constants for all-MiniLM-L6-v2
_SIM_LOW  = 0.25   # was 0.20
_SIM_HIGH = 0.88   # was 0.95

# [S2] Multi-vector component weights
_COMPONENT_WEIGHTS = {
    "skills":      0.50,
    "summary":     0.30,
    "experience":  0.20,
}


def _rescale(sim: float) -> float:
    """
    [S3] Linear rescale from [_SIM_LOW, _SIM_HIGH] → [0.0, 1.0].
    Scores outside the range are clamped.
    """
    if sim <= _SIM_LOW:
        return 0.0
    if sim >= _SIM_HIGH:
        return 1.0
    return (sim - _SIM_LOW) / (_SIM_HIGH - _SIM_LOW)


@dataclass
class SemanticScoreResult:
    """Result of a semantic scoring operation."""
    score:            float  # Rescaled combined score in [0.0, 1.0]
    raw_cosine:       float  # Raw cosine of primary (skills) component
    available:        bool   # False when embedding model was unavailable
    component_scores: dict   = field(default_factory=dict)  # [S6]


class SemanticMatcherService:
    """
    Semantic similarity scorer backed by sentence-transformers.

    Args:
        embedding_service: An EmbeddingService instance (shared singleton).
    """

    def __init__(self, embedding_service):
        self._emb = embedding_service

    @property
    def available(self) -> bool:
        return self._emb.available

    def score(
        self,
        resume_skills: list[str],
        resume_summary: str,
        resume_experience: list[str] | list[dict],
        job_title: str,
        job_description: str,
        job_required_skills: list[str],
        job_responsibilities: list[str] | None = None,
        resume_oov_skills: list[str] | None = None,
        max_text_chars: int = 512,
    ) -> SemanticScoreResult:
        """
        [S1][S2][S4][S6] Compute semantic similarity between a resume and a job.

        Args:
            resume_skills:        Extracted resume skills list.
            resume_summary:       Summary/objective text.
            resume_experience:    List of title strings OR experience dicts.
            job_title:            Job posting title.
            job_description:      Full job description.
            job_required_skills:  Required skills for the job.
            job_responsibilities: Responsibilities list (optional, improves accuracy).
            resume_oov_skills:    Non-standard skills from parser (optional).
            max_text_chars:       Truncation limit per component text.

        Returns:
            SemanticScoreResult with score, raw_cosine, available, component_scores.
        """
        if not self._emb.available:
            return SemanticScoreResult(score=0.0, raw_cosine=0.0, available=False)

        try:
            responsibilities = job_responsibilities or []
            oov_skills       = resume_oov_skills or []

            # [S1] Build component texts
            skills_text_resume  = self._build_skills_text(resume_skills, oov_skills, max_text_chars)
            skills_text_job     = self._build_skills_text(job_required_skills, [], max_text_chars)

            summary_text_resume = (resume_summary or "")[:max_text_chars]
            summary_text_job    = self._build_job_summary_text(job_title, job_description, max_text_chars)

            exp_text_resume = self._build_experience_text(resume_experience, max_text_chars)
            exp_text_job    = self._build_responsibilities_text(
                job_title, responsibilities, job_description, max_text_chars
            )

            # [E2] Batch encode all 6 texts in one call
            all_texts = [
                skills_text_resume, skills_text_job,
                summary_text_resume, summary_text_job,
                exp_text_resume,    exp_text_job,
            ]
            vecs = self._emb.encode(all_texts)

            # [S4] NaN guard
            if np.any(np.isnan(vecs)):
                logger.warning("NaN detected in embedding vectors — returning score=0.0")
                return SemanticScoreResult(score=0.0, raw_cosine=0.0, available=False)

            skills_sim  = float(np.dot(vecs[0], vecs[1]))
            summary_sim = float(np.dot(vecs[2], vecs[3]))
            exp_sim     = float(np.dot(vecs[4], vecs[5]))

            # Clamp to [-1, 1]
            skills_sim  = max(-1.0, min(1.0, skills_sim))
            summary_sim = max(-1.0, min(1.0, summary_sim))
            exp_sim     = max(-1.0, min(1.0, exp_sim))

            # [S2] Combine with component weights
            w = _COMPONENT_WEIGHTS
            combined_raw = (
                w["skills"]     * skills_sim  +
                w["summary"]    * summary_sim +
                w["experience"] * exp_sim
            )

            rescaled = _rescale(combined_raw)

            # [S6] Per-component rescaled scores for explainability
            component_scores = {
                "skills_similarity":     round(_rescale(skills_sim), 4),
                "summary_similarity":    round(_rescale(summary_sim), 4),
                "experience_similarity": round(_rescale(exp_sim), 4),
            }

            return SemanticScoreResult(
                score=round(rescaled, 4),
                raw_cosine=round(skills_sim, 4),   # primary component
                available=True,
                component_scores=component_scores,
            )

        except Exception as exc:
            logger.error("Semantic scoring error: %s", exc, exc_info=True)
            return SemanticScoreResult(score=0.0, raw_cosine=0.0, available=False)

    def score_batch(
        self,
        resume_skills: list[str],
        resume_summary: str,
        resume_experience: list[str] | list[dict],
        jobs: list[dict],
        max_text_chars: int = 512,
    ) -> list[SemanticScoreResult]:
        """
        [S5] Score one resume against multiple jobs in a single encode call.

        Args:
            resume_skills:     Resume skills list.
            resume_summary:    Resume summary text.
            resume_experience: Experience titles or dicts.
            jobs:              List of dicts, each with keys:
                               title, description, required_skills,
                               responsibilities (optional).
            max_text_chars:    Truncation limit per text.

        Returns:
            List of SemanticScoreResult, one per job (same order as input).
        """
        if not self._emb.available:
            return [
                SemanticScoreResult(score=0.0, raw_cosine=0.0, available=False)
                for _ in jobs
            ]

        try:
            oov_skills = []

            # Build resume component texts (encoded once)
            skills_text_r = self._build_skills_text(resume_skills, oov_skills, max_text_chars)
            summary_text_r = (resume_summary or "")[:max_text_chars]
            exp_text_r    = self._build_experience_text(resume_experience, max_text_chars)

            # Build job component texts (one per job)
            job_skills_texts  = []
            job_summary_texts = []
            job_exp_texts     = []

            for j in jobs:
                req_skills    = j.get("required_skills") or []
                title         = j.get("title") or ""
                desc          = j.get("description") or ""
                responsibilities = j.get("responsibilities") or []

                job_skills_texts.append(self._build_skills_text(req_skills, [], max_text_chars))
                job_summary_texts.append(self._build_job_summary_text(title, desc, max_text_chars))
                job_exp_texts.append(
                    self._build_responsibilities_text(title, responsibilities, desc, max_text_chars)
                )

            # Batch encode: 3 resume texts + 3×N job texts
            resume_texts = [skills_text_r, summary_text_r, exp_text_r]
            all_texts    = resume_texts + job_skills_texts + job_summary_texts + job_exp_texts
            all_vecs     = self._emb.encode(all_texts)

            r_skills_vec  = all_vecs[0]
            r_summary_vec = all_vecs[1]
            r_exp_vec     = all_vecs[2]

            N = len(jobs)
            j_skills_vecs  = all_vecs[3:3 + N]
            j_summary_vecs = all_vecs[3 + N:3 + 2*N]
            j_exp_vecs     = all_vecs[3 + 2*N:3 + 3*N]

            results = []
            w = _COMPONENT_WEIGHTS

            for i in range(N):
                skills_sim  = float(np.dot(r_skills_vec,  j_skills_vecs[i]))
                summary_sim = float(np.dot(r_summary_vec, j_summary_vecs[i]))
                exp_sim     = float(np.dot(r_exp_vec,     j_exp_vecs[i]))

                skills_sim  = max(-1.0, min(1.0, skills_sim))
                summary_sim = max(-1.0, min(1.0, summary_sim))
                exp_sim     = max(-1.0, min(1.0, exp_sim))

                combined = (
                    w["skills"]     * skills_sim +
                    w["summary"]    * summary_sim +
                    w["experience"] * exp_sim
                )

                results.append(SemanticScoreResult(
                    score=round(_rescale(combined), 4),
                    raw_cosine=round(skills_sim, 4),
                    available=True,
                    component_scores={
                        "skills_similarity":     round(_rescale(skills_sim), 4),
                        "summary_similarity":    round(_rescale(summary_sim), 4),
                        "experience_similarity": round(_rescale(exp_sim), 4),
                    },
                ))

            return results

        except Exception as exc:
            logger.error("score_batch failed: %s", exc, exc_info=True)
            return [
                SemanticScoreResult(score=0.0, raw_cosine=0.0, available=False)
                for _ in jobs
            ]

    def encode_for_cache(self, text: str):
        """
        Encode text for storage / later reuse.
        Returns numpy.ndarray or None if unavailable.
        """
        if not self._emb.available:
            return None
        try:
            return self._emb.encode(text)
        except Exception:
            return None

    # ── Text builders ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_skills_text(
        skills: list[str],
        oov_skills: list[str],
        max_chars: int,
    ) -> str:
        """
        [S1][S7] Build skills component text.

        Includes OOV skills (non-standard tokens from the parser).
        """
        all_skills = list(skills[:30]) + list(oov_skills[:10])
        if not all_skills:
            return ""
        return ("Skills: " + ", ".join(all_skills))[:max_chars]

    @staticmethod
    def _build_experience_text(
        experience: list[str] | list[dict],
        max_chars: int,
    ) -> str:
        """
        [S1][S7] Build experience component text.

        Accepts either a list of title strings (original format) or a list
        of experience dicts with 'title' and 'impact_points'/'description'.
        """
        parts = []
        for entry in (experience or [])[:5]:
            if isinstance(entry, str):
                parts.append(entry)
            elif isinstance(entry, dict):
                title = entry.get("title") or entry.get("role") or ""
                if title:
                    parts.append(title)
                # [S1] Include bullet points — richer signal than titles alone
                bullets = entry.get("impact_points") or entry.get("bullets") or []
                for b in (bullets or [])[:2]:
                    if b:
                        parts.append(str(b)[:80])

        text = " | ".join(parts)
        return text[:max_chars] if text else ""

    @staticmethod
    def _build_job_summary_text(title: str, description: str, max_chars: int) -> str:
        """[S7] Condense job title + description for summary similarity."""
        parts = []
        if title:
            parts.append(title)
        if description:
            parts.append(description[:300])
        return (". ".join(parts))[:max_chars]

    @staticmethod
    def _build_responsibilities_text(
        title: str,
        responsibilities: list[str],
        description: str,
        max_chars: int,
    ) -> str:
        """
        [S7] Build job responsibilities component text.

        Uses responsibilities list if available, falls back to description.
        """
        parts = []
        if title:
            parts.append(title)
        if responsibilities:
            parts.append("Responsibilities: " + "; ".join(responsibilities[:5]))
        elif description:
            parts.append(description[:300])
        return (". ".join(parts))[:max_chars]