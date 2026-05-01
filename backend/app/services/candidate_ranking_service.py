"""
app/services/candidate_ranking_service.py

Candidate ranking service — returns ranked candidates for a job posting.

Used by recruiters on the job detail page to see applicants sorted
by their ATS match quality.

Ranking strategy:
  1. Fetch all applications for the job.
  2. Look up ATS scores for each applicant's resume × job pair.
  3. Enrich with candidate profile data.
  4. Sort by final_score DESC.
  5. Apply optional stage and score filters.
  6. Return paginated RankedCandidate list.

Usage:
    from app.services.candidate_ranking_service import CandidateRankingService

    svc = CandidateRankingService(
        application_repo=app_repo,
        ats_score_repo=ats_repo,
        candidate_repo=cand_repo,
    )

    result = svc.rank_for_job(
        job_id="abc123",
        stage_filter=None,
        min_score=0.0,
        page=1,
        per_page=20,
    )
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RankedCandidate:
    """A single candidate ranking entry."""
    application_id:  str
    candidate_id:    str
    resume_id:       str
    name:            str
    email:           str
    stage:           str
    final_score:     float
    score_label:     str
    matched_skills:  list = field(default_factory=list)
    missing_skills:  list = field(default_factory=list)
    experience_years: float = 0.0
    skill_count:     int = 0
    location:        str = ""
    summary_text:    str = ""


@dataclass
class RankingResult:
    """Paginated candidate ranking result."""
    candidates:  list[RankedCandidate] = field(default_factory=list)
    total:       int = 0
    page:        int = 1
    per_page:    int = 20
    score_stats: dict = field(default_factory=dict)


class CandidateRankingService:
    """
    Ranks candidates for a job posting by ATS score.
    """

    def __init__(self, application_repo, ats_score_repo, candidate_repo):
        self._app_repo  = application_repo
        self._ats_repo  = ats_score_repo
        self._cand_repo = candidate_repo

    def rank_for_job(
        self,
        job_id: str,
        stage_filter: Optional[str] = None,
        min_score: float = 0.0,
        page: int = 1,
        per_page: int = 20,
    ) -> RankingResult:
        """
        Return ranked candidates for a job.

        Args:
            job_id:       Job UUID.
            stage_filter: Optional ApplicationStage filter.
            min_score:    Minimum ATS final score.
            page:         Pagination page (1-indexed).
            per_page:     Results per page.

        Returns:
            RankingResult with sorted candidates and score stats.
        """
        try:
            return self._run(job_id, stage_filter, min_score, page, per_page)
        except Exception as exc:
            logger.exception("Candidate ranking failed for job=%s", job_id)
            return RankingResult()

    def get_skill_gap_summary(self, job_id: str) -> dict:
        """
        Aggregate skill gap analysis across all applicants for a job.

        Returns:
            {
              "most_common_missing": [...],   # Skills most applicants lack
              "most_common_matched": [...],   # Skills most applicants have
              "avg_match_rate": float,
            }
        """
        try:
            top_scores = self._ats_repo.get_top_for_job(job_id=job_id, top_n=10)
            if not top_scores:
                return {}

            from collections import Counter
            missing_counter: Counter = Counter()
            matched_counter: Counter = Counter()
            total_scores = []

            for score in top_scores:
                for skill in score.missing_skills_list:
                    missing_counter[skill] += 1
                for skill in score.matched_skills_list:
                    matched_counter[skill] += 1
                total_scores.append(score.final_score)

            return {
                "most_common_missing": [s for s, _ in missing_counter.most_common(10)],
                "most_common_matched": [s for s, _ in matched_counter.most_common(10)],
                "avg_match_rate":      round(sum(total_scores) / len(total_scores), 3),
                "applicant_count":     len(top_scores),
            }
        except Exception as exc:
            logger.warning("Skill gap summary failed: %s", exc)
            return {}

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(
        self,
        job_id: str,
        stage_filter: Optional[str],
        min_score: float,
        page: int,
        per_page: int,
    ) -> RankingResult:
        # ── 1. Load applications ──────────────────────────────────────────────
        applications, _ = self._app_repo.list_by_job(
            job_id=job_id,
            stage=stage_filter,
            page=1,
            limit=500,  # Load all then sort by score
        )
        if not applications:
            return RankingResult(page=page, per_page=per_page)

        # ── 2. Load ATS scores ─────────────────────────────────────────────────
        scores_by_resume: dict[str, object] = {}
        scores, _ = self._ats_repo.list_by_job(job_id=job_id, page=1, limit=500)

        for score in scores:
            scores_by_resume[score.resume_id] = score

        # ── 3. Load candidate data ────────────────────────────────────────────
        candidate_ids = list({app.candidate_id for app in applications})
        candidates_by_id = {}
        for cid in candidate_ids:
            cand = self._cand_repo.get_by_id(cid)
            if cand:
                candidates_by_id[cid] = cand

        # ── 4. Build ranked list ──────────────────────────────────────────────
        ranked: list[RankedCandidate] = []
        for app in applications:
            candidate = candidates_by_id.get(app.candidate_id)
            if not candidate:
                continue

            score = scores_by_resume.get(app.resume_id)
            final_score  = score.final_score if score else 0.0
            score_label  = score.score_label if score else "weak"
            matched      = score.matched_skills_list if score else []
            missing      = score.missing_skills_list if score else []
            summary      = score.summary_text if score else ""

            if final_score < min_score:
                continue

            ranked.append(RankedCandidate(
                application_id=app.id,
                candidate_id=candidate.id,
                resume_id=app.resume_id or "",
                name=candidate.full_name,
                email=candidate.email,
                stage=app.stage,
                final_score=final_score,
                score_label=score_label,
                matched_skills=matched,
                missing_skills=missing,
                experience_years=getattr(candidate, "experience_years", 0.0),
                skill_count=len(matched),
                location=candidate.location or "",
                summary_text=summary,
            ))

        # ── 5. Sort by score ─────────────────────────────────────────────────
        ranked.sort(key=lambda r: r.final_score, reverse=True)
        total = len(ranked)

        # ── 6. Paginate ───────────────────────────────────────────────────────
        offset = (page - 1) * per_page
        page_items = ranked[offset: offset + per_page]

        # ── 7. Score stats ────────────────────────────────────────────────────
        all_scores = [r.final_score for r in ranked]
        score_stats = {}
        if all_scores:
            score_stats = {
                "avg":  round(sum(all_scores) / len(all_scores), 3),
                "max":  max(all_scores),
                "min":  min(all_scores),
                "excellent": sum(1 for s in all_scores if s >= 0.80),
                "good":      sum(1 for s in all_scores if 0.65 <= s < 0.80),
                "fair":      sum(1 for s in all_scores if 0.50 <= s < 0.65),
                "weak":      sum(1 for s in all_scores if s < 0.50),
            }

        return RankingResult(
            candidates=page_items,
            total=total,
            page=page,
            per_page=per_page,
            score_stats=score_stats,
        )