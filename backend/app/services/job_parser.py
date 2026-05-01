"""
app/services/job_parser.py

Job description parser — extracts structured data from freeform job postings.

Purpose:
  Recruiters often paste raw job descriptions.  This service normalises them
  into the structured fields our scoring and search layer needs:
    - required_skills / nice_to_have_skills (normalised to vocabulary)
    - responsibilities (bullet list)
    - experience_years (minimum extracted from text)
    - location (extracted or defaulted to 'Remote')
    - additional_requirements (education, work authorisation, etc.)

Design decisions:
  - Pure-regex approach — fast, offline, no ML required.
  - Uses the same _TECH_SKILLS vocabulary as ResumeParserService.
  - Section detection mirrors the resume parser for code reuse.
  - Returns a JobParseResult dataclass — callers decide whether to
    persist the result or show it as a suggestion preview.

Usage:
    from app.services.job_parser import JobParserService
    svc = JobParserService()
    result = svc.parse(raw_description)
    result = svc.parse_job_dict({"title": "...", "description": "..."})
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Import shared skill vocabulary from resume parser
from app.services.resume_parser import _TECH_SKILLS, _SKILL_ALIASES


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class JobParseResult:
    """Structured output of a job description parse."""

    required_skills: list[str] = field(default_factory=list)
    nice_to_have_skills: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    additional_requirements: list[str] = field(default_factory=list)
    experience_years: float = 0.0
    location: str = "Remote"
    parse_error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.parse_error is None


# ─────────────────────────────────────────────────────────────────────────────
# Section headers for job descriptions
# ─────────────────────────────────────────────────────────────────────────────

_JOB_SECTION_PATTERNS = {
    "required_skills":    re.compile(r"^\s*(required\s+skills?|must\s+have|technical\s+requirements?|required\s+qualifications?|minimum\s+qualifications?)\s*[:\-]?\s*$", re.I),
    "nice_to_have":       re.compile(r"^\s*(nice\s+to\s+have|bonus\s+skills?|preferred\s+qualifications?|plus\s+skills?|desired\s+skills?)\s*[:\-]?\s*$", re.I),
    "responsibilities":   re.compile(r"^\s*(responsibilities?|what\s+you.ll\s+do|key\s+duties?|job\s+duties?|role\s+responsibilities?|what\s+the\s+job\s+involves?)\s*[:\-]?\s*$", re.I),
    "requirements":       re.compile(r"^\s*(requirements?|qualifications?|what\s+we.re\s+looking\s+for|about\s+you)\s*[:\-]?\s*$", re.I),
    "additional":         re.compile(r"^\s*(additional\s+requirements?|other\s+requirements?|additional\s+info|benefits?|perks?|what\s+we\s+offer)\s*[:\-]?\s*$", re.I),
}

# Experience extraction patterns
_EXP_PATTERNS = [
    re.compile(r"(\d+)\+?\s*(?:to|\-)\s*(\d+)\s*years?", re.I),   # "3-5 years"
    re.compile(r"(\d+)\+?\s*years?\s+(?:of\s+)?experience", re.I), # "3+ years of experience"
    re.compile(r"minimum\s+(?:of\s+)?(\d+)\s*years?", re.I),       # "minimum 2 years"
    re.compile(r"at\s+least\s+(\d+)\s*years?", re.I),              # "at least 1 year"
]

# Location patterns
_LOCATION_PATTERNS = [
    re.compile(r"location\s*[:\-]?\s*(.+)", re.I),
    re.compile(r"\b(remote|hybrid|on\s*-?\s*site|in\s*-?\s*office)\b", re.I),
    re.compile(r"\b([A-Z][a-z]+(?:,\s*[A-Z]{2})?)\b"),  # City, ST
]


class JobParserService:
    """
    Stateless job description parser.
    """

    def parse(self, description: str) -> JobParseResult:
        """
        Parse a freeform job description string.

        Args:
            description: Raw job posting text.

        Returns:
            JobParseResult — always returns, never raises.
        """
        if not description or not description.strip():
            return JobParseResult(parse_error="Empty job description.")

        try:
            return self._parse_description(description)
        except Exception as exc:
            logger.exception("Job parsing failed")
            return JobParseResult(parse_error=f"Parse error: {exc}")

    def parse_job_dict(self, job_data: dict) -> JobParseResult:
        """
        Parse a job dict (title + description).  Convenience wrapper.

        Args:
            job_data: Dict with at least 'description' key.
                      Optionally 'title' to prepend.

        Returns:
            JobParseResult
        """
        text = ""
        if job_data.get("title"):
            text += f"{job_data['title']}\n\n"
        text += job_data.get("description", "")
        return self.parse(text)

    # ── Core parsing ──────────────────────────────────────────────────────────

    def _parse_description(self, text: str) -> JobParseResult:
        sections = self._segment_sections(text)
        required_skills = self._extract_skills_from_section(
            sections.get("required_skills", "") + "\n" + sections.get("requirements", "")
        )
        nice_to_have = self._extract_skills_from_section(
            sections.get("nice_to_have", "")
        )
        # Remove nice-to-haves from required
        nice_to_have = [s for s in nice_to_have if s not in set(required_skills)]

        # Also mine the full text for any skills not already caught
        all_mentioned = self._extract_skills_from_section(text)
        extra = [s for s in all_mentioned if s not in set(required_skills) and s not in set(nice_to_have)]
        # Put extras in nice_to_have if they weren't already assigned
        nice_to_have = list(dict.fromkeys(nice_to_have + extra[:5]))

        responsibilities = self._extract_bullets(sections.get("responsibilities", ""))
        additional = self._extract_bullets(sections.get("additional", ""))
        experience_years = self._extract_experience_years(text)
        location = self._extract_location(text)

        return JobParseResult(
            required_skills=required_skills,
            nice_to_have_skills=nice_to_have,
            responsibilities=responsibilities,
            additional_requirements=additional,
            experience_years=experience_years,
            location=location,
        )

    # ── Section segmentation ──────────────────────────────────────────────────

    def _segment_sections(self, text: str) -> dict[str, str]:
        lines = text.split("\n")
        sections: dict[str, str] = {}
        current = "intro"
        buffer: list[str] = []

        for line in lines:
            stripped = line.strip()
            matched = None
            for name, pattern in _JOB_SECTION_PATTERNS.items():
                if pattern.match(stripped):
                    matched = name
                    break
            if matched:
                sections[current] = "\n".join(buffer).strip()
                current = matched
                buffer = []
            else:
                buffer.append(line)

        sections[current] = "\n".join(buffer).strip()
        return sections

    # ── Skill extraction ──────────────────────────────────────────────────────

    def _extract_skills_from_section(self, text: str) -> list[str]:
        text_lower = text.lower()
        found: set[str] = set()
        for skill in sorted(_TECH_SKILLS, key=len, reverse=True):
            if re.search(r"\b" + re.escape(skill) + r"\b", text_lower):
                found.add(_SKILL_ALIASES.get(skill, skill))
        return sorted(found)

    # ── Bullet/list extraction ────────────────────────────────────────────────

    def _extract_bullets(self, text: str) -> list[str]:
        if not text.strip():
            return []
        bullets = []
        for line in text.split("\n"):
            line = line.strip().lstrip("•-*·►▪✓✔").strip()
            if len(line) > 10:
                bullets.append(line[:300])
        return bullets[:15]

    # ── Experience years ──────────────────────────────────────────────────────

    def _extract_experience_years(self, text: str) -> float:
        for pattern in _EXP_PATTERNS:
            m = pattern.search(text)
            if m:
                try:
                    # If range pattern, take lower bound
                    years = float(m.group(1))
                    return min(years, 20.0)
                except (ValueError, IndexError):
                    pass
        return 0.0

    # ── Location ──────────────────────────────────────────────────────────────

    def _extract_location(self, text: str) -> str:
        # Check for explicit location: field
        m = re.search(r"location\s*[:\-]\s*(.{3,80})", text, re.I)
        if m:
            loc = m.group(1).split("\n")[0].strip()
            if loc:
                return loc[:100]

        # Check for remote/hybrid/on-site keywords
        m = re.search(r"\b(fully\s+remote|remote\s+only|remote\s+first|remote)\b", text, re.I)
        if m:
            return "Remote"
        m = re.search(r"\bhybrid\b", text, re.I)
        if m:
            return "Hybrid"
        m = re.search(r"\b(on.?site|in.?office)\b", text, re.I)
        if m:
            return "On-site"

        return "Remote"