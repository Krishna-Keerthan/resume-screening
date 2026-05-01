"""
app/services/keyword_matcher.py

BM25-based lexical keyword matcher.

Computes a keyword match score between a candidate's resume and a job posting
using two complementary strategies:

  1. BM25 (rank-bm25):
       Treats the job description as a query and the resume as a document.
       BM25 is better than TF-IDF for this use case because it penalises
       very long documents that happen to contain many keyword hits.

  2. Skill overlap ratio:
       Direct set-intersection between extracted skills.
       Required skills are weighted 2x vs nice-to-have skills.
       This catches abbreviated / normalised skill names that BM25 misses.

Final score:
       0.60 * bm25_normalised + 0.40 * skill_overlap

Graceful degradation:
       If rank-bm25 is not installed, falls back to simple TF overlap.

Usage:
    from app.services.keyword_matcher import KeywordMatcherService
    svc = KeywordMatcherService()
    score = svc.score(
        resume_text="Python developer with 5 years React experience...",
        resume_skills=["python", "react"],
        job_description="We need a Python/React developer...",
        job_required_skills=["python", "react", "typescript"],
        job_nice_to_have_skills=["graphql"],
    )
    # Returns float in [0.0, 1.0]
"""

import logging
import math
import re
from typing import Optional

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return [t for t in text.split() if len(t) > 1]


class KeywordMatcherService:
    """
    BM25 + skill-overlap lexical scorer.

    Stateless — safe to reuse across requests.
    """

    # BM25 parameters (standard defaults)
    _K1: float = 1.5
    _B:  float = 0.75

    def score(
        self,
        resume_text: str,
        resume_skills: list[str],
        job_description: str,
        job_required_skills: list[str],
        job_nice_to_have_skills: Optional[list[str]] = None,
        oov_skills: Optional[list[str]] = None,
        bm25_weight: float = 0.60,
        overlap_weight: float = 0.40,
    ) -> float:
        """
        Compute keyword match score between a resume and a job.

        Args:
            resume_text:              Full resume raw text.
            resume_skills:            Extracted skills from resume.
            job_description:          Full job description text.
            job_required_skills:      Required skills from job.
            job_nice_to_have_skills:  Nice-to-have skills from job.
            bm25_weight:              Weight for BM25 component (default 0.60).
            overlap_weight:           Weight for skill overlap (default 0.40).

        Returns:
            Float in [0.0, 1.0].
        """
        nice_to_have = job_nice_to_have_skills or []

        bm25_score = self._bm25_score(
            document=resume_text or " ".join(resume_skills),
            query=job_description or " ".join(job_required_skills),
        )

        overlap_score = self._skill_overlap_score(
            resume_skills=resume_skills,
            required_skills=job_required_skills,
            nice_to_have_skills=nice_to_have,
        )

        combined = bm25_weight * bm25_score + overlap_weight * overlap_score

        # OOV skills boost: unrecognised skills from resume that appear in
        # job description get a 0.5x contribution (half-weight, cautious).
        if oov_skills:
            job_text_lower = (job_description or "").lower()
            oov_matches = sum(
                1 for s in oov_skills
                if s.lower() in job_text_lower
            )
            if job_required_skills:
                oov_boost = 0.5 * (oov_matches / max(len(job_required_skills), 1))
                combined = min(1.0, combined + oov_boost * overlap_weight)

        return round(min(1.0, max(0.0, combined)), 4)

    # ── BM25 ──────────────────────────────────────────────────────────────────

    def _bm25_score(self, document: str, query: str) -> float:
        """
        Compute normalised BM25 score.

        Treats the single resume as the corpus (one document), so BM25
        reduces to TF-IDF-like weighting for single-document scoring.
        Returns score normalised to [0.0, 1.0].
        """
        doc_tokens = _tokenize(document)
        query_tokens = _tokenize(query)

        if not doc_tokens or not query_tokens:
            return 0.0

        # Try rank-bm25 for proper BM25
        try:
            from rank_bm25 import BM25Okapi
            bm25 = BM25Okapi([doc_tokens])
            scores = bm25.get_scores(query_tokens)
            raw = float(scores[0])
            # Normalise: raw BM25 scores are unbounded, sigmoid-normalise
            normalised = self._sigmoid_normalise(raw, scale=10.0)
            return normalised
        except ImportError:
            pass

        # Fallback: simple term-frequency overlap
        return self._tf_overlap(doc_tokens, query_tokens)

    def _tf_overlap(self, doc_tokens: list[str], query_tokens: list[str]) -> float:
        """Simple TF overlap fallback when rank-bm25 is not installed."""
        if not query_tokens:
            return 0.0
        doc_set = set(doc_tokens)
        matched = sum(1 for t in query_tokens if t in doc_set)
        return matched / len(set(query_tokens))

    @staticmethod
    def _sigmoid_normalise(x: float, scale: float = 10.0) -> float:
        """Map any positive float to (0, 1) using a scaled sigmoid."""
        try:
            return 1.0 / (1.0 + math.exp(-x / scale))
        except OverflowError:
            return 1.0 if x > 0 else 0.0

    # ── Skill overlap ─────────────────────────────────────────────────────────

    def _normalise_skill(self, skill: str) -> str:
        """Normalise a skill string using synonym map."""
        try:
            from app.services.skill_taxonomy import SKILL_SYNONYMS
            return SKILL_SYNONYMS.get(skill.lower().strip(), skill.lower().strip())
        except ImportError:
            return skill.lower().strip()

    def _skill_overlap_score(
        self,
        resume_skills: list[str],
        required_skills: list[str],
        nice_to_have_skills: list[str],
    ) -> float:
        # Normalise all skills through synonym map before comparison
        resume_set = {self._normalise_skill(s) for s in resume_skills}
        req_set    = {self._normalise_skill(s) for s in required_skills}
        nth_set    = {self._normalise_skill(s) for s in nice_to_have_skills}

        matched_req = len(resume_set & req_set)
        matched_nth = len(resume_set & nth_set)
        numerator   = 2 * matched_req + matched_nth
        denominator = 2 * len(req_set) + len(nth_set)
        if denominator == 0:
            return 0.0
        return min(1.0, numerator / denominator)

    def get_skill_breakdown(
        self,
        resume_skills: list[str],
        job_required_skills: list[str],
        job_nice_to_have_skills: Optional[list[str]] = None,
    ) -> dict:
        nice_to_have = job_nice_to_have_skills or []
        resume_set   = {self._normalise_skill(s) for s in resume_skills}
        all_job      = {self._normalise_skill(s) for s in job_required_skills + nice_to_have}
        req_set      = {self._normalise_skill(s) for s in job_required_skills}

        return {
            "matched": sorted(resume_set & all_job),
            "missing": sorted(req_set - resume_set),
            "extra":   sorted(resume_set - all_job)[:10],
        }