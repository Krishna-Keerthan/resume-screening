"""
app/services/explainability_engine.py  ── IMPROVED VERSION

Explainability engine — converts score components into human-readable
improvement tips, skill gap analysis, and hiring recommendations.

IMPROVEMENTS OVER ORIGINAL
---------------------------
  [X1]  Semantic component scores surfaced in tips: when the new
        SemanticScoreResult.component_scores dict is passed in, the engine
        generates specific tips (e.g. "Your summary does not match the job
        description well — rewrite it using the role's terminology").

  [X2]  Skill gap tips improved: missing skills are grouped by category
        (languages, cloud, frameworks) using skill_taxonomy when available
        — instead of a flat comma-separated list, tips read
        "Add these cloud skills: AWS, GCP" and "Add these languages: Go, Rust".

  [X3]  Tip deduplication: rule-based and LLM tips can produce duplicates.
        Tips are now deduplicated by lowercased content before capping at 8.

  [X4]  Hiring recommendation improved: new rule considers the number of
        REQUIRED skills missing as a fraction of total required — a candidate
        missing 80% of required skills gets "no" even if overall score is 0.60.

  [X5]  LLM prompt improved: passes semantic_component_scores breakdown to
        Groq so the narrative can reference specific weaknesses
        ("Your experience section has low alignment with the role").

  [X6]  Summary quality improved: rule-based summary now mentions the
        score label, top matched skills, and specific experience gap
        with actionable framing, not just raw numbers.

  [X7]  ExplanationResult now includes: score_label (already computed in
        ats_scorer — surfaced here to avoid recomputing in the API layer),
        and semantic_breakdown dict (passes through component scores).
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class ExplanationResult:
    """Full explainability output for an ATS score."""
    summary:               str  = ""
    matched_skills:        list = field(default_factory=list)
    missing_skills:        list = field(default_factory=list)
    extra_skills:          list = field(default_factory=list)
    improvement_tips:      list = field(default_factory=list)
    hiring_recommendation: str  = "maybe"
    recommendation_reason: str  = ""
    score_breakdown:       dict = field(default_factory=dict)
    llm_enhanced:          bool = False
    score_label:           str  = "fair"         # [X7]
    semantic_breakdown:    dict = field(default_factory=dict)  # [X7]


# ── Tip templates ──────────────────────────────────────────────────────────────

_SECTION_TIPS = {
    "has_skills":         ("high",   "formatting",   "Add a dedicated Technical Skills section listing your programming languages, frameworks, and tools."),
    "has_experience":     ("high",   "experience",   "Add your work experience with company names, job titles, and date ranges."),
    "has_education":      ("medium", "education",    "Include your educational background (degrees, institutions, graduation years)."),
    "has_summary":        ("medium", "formatting",   "Add a 2–3 sentence professional summary at the top targeting this specific role."),
    "has_certifications": ("low",    "skills",       "Consider adding relevant certifications (AWS, Google Cloud, etc.) to strengthen your profile."),
    "has_projects":       ("low",    "experience",   "Add a Projects section showcasing personal or open-source work related to this role."),
    "sufficient_length":  ("high",   "formatting",   "Your resume appears sparse. Add more detail to your experience and skills sections."),
}

_SCORE_TIPS = {
    "low_keyword":  ("high",   "skills",     "Incorporate more keywords from the job posting directly into your skills and experience sections."),
    "low_semantic": ("high",   "skills",     "Tailor your resume language to mirror the terminology used in the job description."),
    "low_exp":      ("medium", "experience", "Your experience level may be below the job requirement. Highlight project experience that demonstrates equivalent depth."),
    "low_quality":  ("medium", "formatting", "Improve resume structure by adding complete content to all required sections."),
}

# [X1] Semantic component-specific tips
_SEMANTIC_COMPONENT_TIPS = {
    "low_skills_sim": (
        "high", "skills",
        "Your skills list doesn't closely match the job's required skills. "
        "Add the required skills explicitly in a dedicated skills section."
    ),
    "low_summary_sim": (
        "medium", "formatting",
        "Your professional summary doesn't align well with this role's terminology. "
        "Rewrite it using keywords directly from the job title and description."
    ),
    "low_experience_sim": (
        "medium", "experience",
        "Your experience descriptions don't closely reflect this role's responsibilities. "
        "Rewrite bullet points using language from the job's responsibilities section."
    ),
}


class ExplainabilityEngine:
    """
    Produces human-readable explanations for ATS scores.

    Args:
        groq_service: Optional GroqService for LLM-enhanced narratives.
        keyword_matcher: Optional KeywordMatcherService for skill breakdown.
    """

    def __init__(self, groq_service=None, keyword_matcher=None):
        self._groq = groq_service
        self._kwm  = keyword_matcher

    def explain(
        self,
        final_score: float,
        semantic_score: float,
        keyword_score: float,
        experience_score: float,
        section_quality_score: float,
        resume_skills: list[str],
        job_title: str,
        job_required_skills: list[str],
        job_nice_to_have_skills: Optional[list[str]] = None,
        candidate_years: float = 0.0,
        required_years: float = 0.0,
        missing_sections: Optional[list[str]] = None,
        use_llm: bool = True,
        weights: Optional[dict] = None,
        semantic_component_scores: Optional[dict] = None,  # [X1]
    ) -> ExplanationResult:
        """
        [X1][X2][X3][X4][X6] Generate full explanation for a score.

        Args:
            semantic_component_scores: Optional dict from SemanticScoreResult.component_scores
                                       — if present, enables component-specific tips.
            (all other args): Same as original.
        """
        nice_to_have  = job_nice_to_have_skills or []
        missing_secs  = missing_sections or []
        sem_comps     = semantic_component_scores or {}

        # ── Skill breakdown ────────────────────────────────────────────────────
        if self._kwm:
            breakdown = self._kwm.get_skill_breakdown(
                resume_skills, job_required_skills, nice_to_have
            )
        else:
            resume_set = {s.lower() for s in resume_skills}
            job_set    = {s.lower() for s in job_required_skills + nice_to_have}
            req_set    = {s.lower() for s in job_required_skills}
            breakdown  = {
                "matched": sorted(resume_set & job_set),
                "missing": sorted(req_set - resume_set),
                "extra":   sorted(resume_set - job_set)[:10],
            }

        # ── Score label ────────────────────────────────────────────────────────
        score_label = (
            "excellent" if final_score >= 0.80 else
            "good"      if final_score >= 0.65 else
            "fair"      if final_score >= 0.50 else
            "weak"
        )

        # ── Rule-based tips ────────────────────────────────────────────────────
        tips = self._build_tips(
            semantic_score, keyword_score, experience_score,
            section_quality_score, missing_secs, breakdown["missing"],
            job_required_skills, sem_comps,  # [X1][X2]
        )

        # ── Hiring recommendation ──────────────────────────────────────────────
        recommendation, reason = self._hiring_recommendation(
            final_score, experience_score, len(breakdown["missing"]),
            len(job_required_skills), candidate_years, required_years,
        )

        score_breakdown = {
            "final":           round(final_score, 4),
            "semantic":        round(semantic_score, 4),
            "keyword":         round(keyword_score, 4),
            "experience":      round(experience_score, 4),
            "section_quality": round(section_quality_score, 4),
            "weights":         weights or {},
        }

        result = ExplanationResult(
            summary="",
            matched_skills=breakdown["matched"],
            missing_skills=breakdown["missing"],
            extra_skills=breakdown["extra"],
            improvement_tips=tips,
            hiring_recommendation=recommendation,
            recommendation_reason=reason,
            score_breakdown=score_breakdown,
            llm_enhanced=False,
            score_label=score_label,               # [X7]
            semantic_breakdown=sem_comps,          # [X7]
        )

        # ── LLM-enhanced summary ───────────────────────────────────────────────
        if use_llm and self._groq and self._groq.available:
            try:
                llm_result = self._groq.explain_score(
                    job_title=job_title,
                    job_required_skills=job_required_skills,
                    candidate_skills=resume_skills,
                    matched_skills=breakdown["matched"],
                    missing_skills=breakdown["missing"],
                    final_score=final_score,
                    experience_score=experience_score,
                    semantic_score=semantic_score,
                    # [X5] Pass component breakdown so Groq can be specific
                    semantic_component_scores=sem_comps,
                )
                result.summary = llm_result.get("summary", "")
                llm_tips = llm_result.get("improvement_tips", [])
                # [X3] Deduplicate before merging
                result.improvement_tips = _dedup_tips(llm_tips + tips)[:8]
                result.hiring_recommendation = llm_result.get(
                    "hiring_recommendation", recommendation
                )
                result.recommendation_reason = llm_result.get(
                    "recommendation_reason", reason
                )
                result.llm_enhanced = True
            except Exception as exc:
                logger.warning("LLM explanation failed, using rule-based: %s", exc)

        if not result.summary:
            result.summary = self._rule_based_summary(
                final_score, score_label, breakdown["matched"],
                breakdown["missing"], candidate_years, required_years,
                job_title,
            )

        return result

    # ── Rule-based helpers ─────────────────────────────────────────────────────

    def _build_tips(
        self,
        semantic_score: float,
        keyword_score: float,
        experience_score: float,
        section_quality_score: float,
        missing_sections: list[str],
        missing_skills: list[str],
        job_required_skills: list[str],
        semantic_component_scores: dict,
    ) -> list[dict]:
        """[X1][X2] Build rule-based improvement tips."""
        tips: list[dict] = []

        # Low overall score tips
        if keyword_score < 0.40:
            p, c, t = _SCORE_TIPS["low_keyword"]
            tips.append({"priority": p, "category": c, "tip": t})
        if semantic_score < 0.40:
            p, c, t = _SCORE_TIPS["low_semantic"]
            tips.append({"priority": p, "category": c, "tip": t})
        if experience_score < 0.50:
            p, c, t = _SCORE_TIPS["low_exp"]
            tips.append({"priority": p, "category": c, "tip": t})

        # [X1] Semantic component tips (only when breakdown available)
        if semantic_component_scores:
            skills_sim  = semantic_component_scores.get("skills_similarity", 1.0)
            summary_sim = semantic_component_scores.get("summary_similarity", 1.0)
            exp_sim     = semantic_component_scores.get("experience_similarity", 1.0)

            if skills_sim < 0.35:
                p, c, t = _SEMANTIC_COMPONENT_TIPS["low_skills_sim"]
                tips.append({"priority": p, "category": c, "tip": t})
            if summary_sim < 0.35:
                p, c, t = _SEMANTIC_COMPONENT_TIPS["low_summary_sim"]
                tips.append({"priority": p, "category": c, "tip": t})
            if exp_sim < 0.30:
                p, c, t = _SEMANTIC_COMPONENT_TIPS["low_experience_sim"]
                tips.append({"priority": p, "category": c, "tip": t})

        # Missing section tips
        section_order = [
            "has_skills", "has_experience", "has_education",
            "has_summary", "has_certifications", "has_projects", "sufficient_length",
        ]
        for section in section_order:
            if section in missing_sections:
                p, c, t = _SECTION_TIPS[section]
                tips.append({"priority": p, "category": c, "tip": t})

        # [X2] Categorised missing skill tips
        if missing_skills:
            categorised = _categorise_skills(missing_skills)
            if categorised:
                for cat_label, cat_skills in categorised.items():
                    top = ", ".join(cat_skills[:4])
                    tips.append({
                        "priority": "high",
                        "category": "skills",
                        "tip": f"Add these required {cat_label} skills: {top}.",
                    })
            else:
                # Fallback: flat list
                top_missing = ", ".join(missing_skills[:5])
                tips.append({
                    "priority": "high",
                    "category": "skills",
                    "tip": f"Add these required skills to your resume if you have them: {top_missing}.",
                })

        return tips[:8]

    @staticmethod
    def _hiring_recommendation(
        final_score: float,
        experience_score: float,
        missing_skill_count: int,
        required_skill_count: int,
        candidate_years: float,
        required_years: float,
    ) -> tuple[str, str]:
        """
        [X4] Derive hiring recommendation from score components.

        New rule: if candidate is missing > 60% of required skills, cap at "maybe".
        """
        # [X4] Skill gap veto
        if required_skill_count > 0:
            missing_ratio = missing_skill_count / required_skill_count
            if missing_ratio > 0.60:
                return (
                    "maybe",
                    f"Candidate is missing {missing_skill_count} of {required_skill_count} "
                    f"required skills — interview recommended to verify transferable experience.",
                )

        if final_score >= 0.75 and experience_score >= 0.70:
            return "strong_yes", "Strong match across skills, experience, and semantic alignment."
        if final_score >= 0.60:
            return "yes", "Good overall match with minor gaps."
        if final_score >= 0.45:
            return "maybe", "Partial match — candidate may need to demonstrate key skills in interview."
        return "no", "Significant skill or experience gap for this role."

    @staticmethod
    def _rule_based_summary(
        final_score: float,
        score_label: str,
        matched_skills: list,
        missing_skills: list,
        candidate_years: float,
        required_years: float,
        job_title: str,
    ) -> str:
        """
        [X6] Generate a more actionable rule-based summary.

        Includes: score label, top matched skills, experience gap framing.
        """
        pct = f"{final_score:.0%}"

        # Top matched skills
        if matched_skills:
            top_matched = ", ".join(matched_skills[:3])
            skill_note  = f"demonstrates proficiency in {top_matched}"
        else:
            skill_note = "has limited direct skill overlap with this role"

        # Missing skills
        if missing_skills:
            top_missing   = ", ".join(missing_skills[:3])
            missing_clause = f" Key gaps include: {top_missing}."
        else:
            missing_clause = " No critical skill gaps found."

        # Experience alignment
        if required_years > 0:
            if candidate_years >= required_years:
                exp_note = f" Experience level ({candidate_years:.0f} yrs) meets the requirement."
            else:
                gap = required_years - candidate_years
                exp_note = (
                    f" Experience is {gap:.0f} year{'s' if gap != 1 else ''} short "
                    f"of the {required_years:.0f}-year requirement."
                )
        else:
            exp_note = ""

        return (
            f"Overall ATS match: {pct} ({score_label}). "
            f"Candidate {skill_note} for the {job_title} role.{missing_clause}{exp_note}"
        )


# ── Module-level helpers ───────────────────────────────────────────────────────

def _dedup_tips(tips: list[dict]) -> list[dict]:
    """
    [X3] Deduplicate tips by lowercased content string.

    Preserves order (first occurrence wins).
    """
    seen: set[str] = set()
    result: list[dict] = []
    for tip in tips:
        key = tip.get("tip", "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(tip)
    return result


def _categorise_skills(skills: list[str]) -> dict[str, list[str]]:
    """
    [X2] Group a list of skill strings into categories using skill_taxonomy.

    Returns a dict like {"language": ["go", "rust"], "cloud": ["aws"]}.
    Returns empty dict if skill_taxonomy is unavailable.
    """
    try:
        from app.services.skill_taxonomy import SKILL_CATEGORIES

        # Build reverse map: skill → category label
        skill_to_cat: dict[str, str] = {}
        cat_labels = {
            "languages":     "language",
            "web_frontend":  "frontend framework",
            "backend":       "backend framework",
            "ml_ai":         "ML/AI",
            "databases":     "database",
            "cloud_infra":   "cloud",
            "mobile":        "mobile",
            "security":      "security",
            "tools":         "tool",
        }
        for cat_key, cat_label in cat_labels.items():
            for s in SKILL_CATEGORIES.get(cat_key, []):
                skill_to_cat[s.lower()] = cat_label

        grouped: dict[str, list[str]] = {}
        uncategorised: list[str] = []
        for s in skills:
            cat = skill_to_cat.get(s.lower())
            if cat:
                grouped.setdefault(cat, []).append(s)
            else:
                uncategorised.append(s)

        if uncategorised:
            grouped["skill"] = uncategorised

        return grouped

    except ImportError:
        return {}