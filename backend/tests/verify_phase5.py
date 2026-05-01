#!/usr/bin/env python3
"""
tests/verify_phase5.py

Static source analysis verifying Phase 5 test suite completeness.
Checks file existence, test class names, test method names, and
that critical assertions are present in the source.

Run from repo root:
    python tests/verify_phase5.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")

PASS = 0
FAIL = 0
RESULTS = []


def check(name: str, cond: bool, msg: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        RESULTS.append(f"  ✓  {name}")
    else:
        FAIL += 1
        RESULTS.append(f"  ✗  {name}" + (f"  ← {msg}" if msg else ""))


def read(rel_path: str) -> str:
    full = os.path.join(TESTS, rel_path)
    if os.path.exists(full):
        return open(full).read()
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: File existence
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 1] Test file existence")

required_files = [
    "conftest.py",
    "integration/test_health.py",
    "integration/test_candidates.py",
    "integration/test_recruiters.py",
    "integration/test_jobs.py",
    "integration/test_resumes.py",
    "integration/test_applications.py",
    "integration/test_scoring.py",
    "integration/test_analytics.py",
    "integration/e2e/__init__.py",
    "integration/e2e/test_e2e_candidate_flow.py",
    "integration/e2e/test_e2e_recruiter_flow.py",
    "unit/test_enums.py",
    "unit/test_models.py",
    "unit/test_exceptions.py",
    "unit/test_responses.py",
    "unit/test_schemas.py",
    "unit/test_services.py",
]

for f in required_files:
    full = os.path.join(TESTS, f)
    check(f"exists: {f}", os.path.exists(full))


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: conftest.py fixtures
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 2] conftest.py fixtures")
conf = read("conftest.py")

fixtures = [
    "def app",
    "def db",
    "def client",
    "def json_post",
    "def json_patch",
    "def json_get",
    "def json_delete",
    "def sample_candidate",
    "def sample_recruiter",
    "def sample_job",
    "def sample_job_closed",
    "def sample_resume",
    "def sample_application",
    "def mock_services",
    "def resume_file",
]
for f in fixtures:
    check(f"fixture: {f}", f in conf)

check("ServiceFactory.create_all patched",
      "ServiceFactory.create_all" in conf)
check("rollback after each test", "transaction.rollback()" in conf)
check("sample_application links resume", "resume_id=sample_resume.id" in conf or
      "resume_id" in conf)


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Health tests
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 3] Health integration tests")
health = read("integration/test_health.py")

health_checks = [
    "TestLiveness",
    "TestReadiness",
    "TestServiceStatus",
    "TestErrorHandlers",
    "uptime_seconds",
    "status_code == 200",
    "status_code == 404",
    "status_code == 405",
    "error_code",
    "NOT_FOUND",
]
for c in health_checks:
    check(f"health: {c}", c in health)


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Candidate tests
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 4] Candidate integration tests")
cands = read("integration/test_candidates.py")

candidate_checks = [
    "TestListCandidates",
    "TestCreateCandidate",
    "TestGetCandidate",
    "TestUpdateCandidate",
    "TestDeleteCandidate",
    "TestCandidateResumes",
    "status_code == 409",           # duplicate email
    "CANDIDATE_EMAIL_CONFLICT",
    "status_code == 404",           # not found
    "CANDIDATE_NOT_FOUND",
    "status_code == 400",           # validation
    "status_code == 415",           # wrong file type
    "NO_FILE_UPLOADED",
    "pagination_meta",
    "open_to_work",
]
for c in candidate_checks:
    check(f"candidate: {c}", c in cands)

check("candidate: soft-delete or 204",
      "soft_delete" in cands or "status_code == 204" in cands)


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Recruiter tests
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 5] Recruiter integration tests")
recs = read("integration/test_recruiters.py")

recruiter_checks = [
    "TestListRecruiters",
    "TestCreateRecruiter",
    "TestGetRecruiter",
    "TestUpdateRecruiter",
    "TestDeleteRecruiter",
    "TestRecruiterJobs",
    "RECRUITER_EMAIL_CONFLICT",
    "RECRUITER_NOT_FOUND",
    "filter_by_status",
]
for c in recruiter_checks:
    check(f"recruiter: {c}", c in recs)


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Job tests
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 6] Job integration tests")
jobs = read("integration/test_jobs.py")

job_checks = [
    "TestListJobs",
    "TestCreateJob",
    "TestGetJob",
    "TestUpdateJob",
    "TestDeleteJob",
    "JOB_NOT_FOUND",
    "default_status_active",
    "required_skills_saved",
    "closed_job_not_in_default_list",
    "invalid_salary_range_400",
    "description_too_short_400",
]
for c in job_checks:
    check(f"job: {c}", c in jobs)


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Resume tests
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 7] Resume integration tests")
resumes = read("integration/test_resumes.py")

resume_checks = [
    "TestListResumes",
    "TestGetResume",
    "TestDeleteResume",
    "TestAnalyzeResume",
    "TestScorePreview",
    "RESUME_NOT_FOUND",
    "MISSING_PARAM",
    "preview",
    "score_raw",
    "filter_by_candidate_id",
    "filter_by_parse_status",
    "invalid_parse_status_400",
]
for c in resume_checks:
    check(f"resume: {c}", c in resumes)


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Application tests
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 8] Application integration tests")
apps = read("integration/test_applications.py")

app_checks = [
    "TestListApplications",
    "TestCreateApplication",
    "TestGetApplication",
    "TestUpdateApplicationStage",
    "TestWithdrawApplication",
    "DUPLICATE_APPLICATION",
    "JOB_NOT_ACTIVE",
    "RESUME_OWNERSHIP_MISMATCH",
    "CANNOT_WITHDRAW",
    "stage_is_applied",
    "advance_to_reviewed",
    "rejection_reason_saved",
    "recruiter_notes_saved",
    "cannot_withdraw_hired",
    "filter_by_job_id",
    "filter_by_candidate_id",
    "filter_by_stage",
]
for c in app_checks:
    check(f"application: {c}", c in apps)


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Scoring tests
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 9] Scoring integration tests")
scoring = read("integration/test_scoring.py")

scoring_checks = [
    "TestMatchEndpoint",
    "TestRankCandidatesEndpoint",
    "TestJobRecommendationsEndpoint",
    "TestSkillGapEndpoint",
    "TestListScores",
    "preview_mode_200",
    "persist_mode_201",
    "save_result",
    "preview",
    "matched_skills",
    "missing_skills",
    "filter_by_resume_id",
    "filter_by_min_score",
]
for c in scoring_checks:
    check(f"scoring: {c}", c in scoring)


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: Analytics tests
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 10] Analytics integration tests")
analytics = read("integration/test_analytics.py")

analytics_checks = [
    "TestDashboard",
    "TestPipeline",
    "TestScoreDistribution",
    "TestSkillsDemand",
    "TestTopJobs",
    "missing_recruiter_id_400",
    "nonexistent_recruiter_404",
    "pipeline_funnel",
    "score_distribution",
    "skills",
    "top_n_param",
]
for c in analytics_checks:
    check(f"analytics: {c}", c in analytics)


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: End-to-end flow tests
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 11] E2E flow tests")
e2e_c = read("integration/e2e/test_e2e_candidate_flow.py")
e2e_r = read("integration/e2e/test_e2e_recruiter_flow.py")

e2e_checks = [
    ("candidate: full_flow",               "test_full_flow" in e2e_c),
    ("candidate: duplicate_blocked",        "test_duplicate_application_blocked" in e2e_c),
    ("candidate: closed_job_blocked",       "test_closed_job_blocks_application" in e2e_c),
    ("candidate: multipart upload in flow", "multipart/form-data" in e2e_c),
    ("candidate: stage progression",        "reviewed" in e2e_c and "shortlisted" in e2e_c),
    ("recruiter: full_cycle",               "test_recruiter_full_cycle" in e2e_r),
    ("recruiter: jobs list check",          "/api/v1/recruiters" in e2e_r),
    ("recruiter: analytics in flow",        "/api/v1/analytics/dashboard" in e2e_r),
    ("recruiter: close job in flow",        "closed" in e2e_r),
    ("recruiter: soft-delete in flow",      "status_code == 404" in e2e_r),
]
for name, cond in e2e_checks:
    check(f"e2e: {name}", cond)


# ─────────────────────────────────────────────────────────────────────────────
# Test 12: Unit tests
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 12] Unit tests")
enums    = read("unit/test_enums.py")
models   = read("unit/test_models.py")
excepts  = read("unit/test_exceptions.py")
resps    = read("unit/test_responses.py")
schemas  = read("unit/test_schemas.py")
svcs     = read("unit/test_services.py")

unit_checks = [
    ("enums: ApplicationStage values",    "APPLIED" in enums),
    ("enums: TERMINAL_STAGES",            "TERMINAL_STAGES" in enums),
    ("enums: STAGE_TRANSITIONS",          "STAGE_TRANSITIONS" in enums),
    ("enums: score_to_label",             "score_to_label" in enums),
    ("enums: boundary tests",             "boundary" in enums),
    ("models: soft_delete tested",        "soft_delete" in models),
    ("models: skills list roundtrip",     "skills_list_roundtrip" in models),
    ("models: advance_stage",             "advance_stage" in models),
    ("models: stage_history",             "stage_history" in models),
    ("exceptions: NotFoundException",     "NotFoundException" in excepts),
    ("exceptions: ConflictException",     "ConflictException" in excepts),
    ("exceptions: ForbiddenException",    "ForbiddenException" in excepts),
    ("responses: success_list",           "TestSuccessListResponse" in resps),
    ("responses: total_pages_calculated", "total_pages_calculated" in resps),
    ("responses: has_next/has_prev",      "has_next" in resps and "has_prev" in resps),
    ("schemas: salary cross-validator",   "salary_cross_validator" in schemas),
    ("schemas: email lowercase",          "email_normalised_to_lowercase" in schemas),
    ("schemas: invalid company_size",     "invalid_company_size" in schemas),
    ("services: KeywordMatcher",          "TestKeywordMatcher" in svcs),
    ("services: ExperienceScorer",        "TestExperienceScorer" in svcs),
    ("services: SectionQualityScorer",    "TestSectionQualityScorer" in svcs),
    ("services: case insensitive match",  "case_insensitive" in svcs),
    ("services: extra skills captured",   "extra_skills" in svcs),
    ("services: education bonus",         "education_bonus" in svcs),
]
for name, cond in unit_checks:
    check(f"unit: {name}", cond)


# ─────────────────────────────────────────────────────────────────────────────
# Test 13: Test count  
# ─────────────────────────────────────────────────────────────────────────────
print("\n[Test 13] Minimum test count per file")

import re

def count_tests(rel_path: str) -> int:
    src = read(rel_path)
    return len(re.findall(r"\bdef test_\w+", src))


min_tests = {
    "integration/test_health.py":       10,
    "integration/test_candidates.py":   25,
    "integration/test_recruiters.py":   18,
    "integration/test_jobs.py":         20,
    "integration/test_resumes.py":      16,
    "integration/test_applications.py": 22,
    "integration/test_scoring.py":      16,
    "integration/test_analytics.py":    16,
    "unit/test_enums.py":               15,
    "unit/test_models.py":              18,
    "unit/test_exceptions.py":           8,
    "unit/test_responses.py":           12,
    "unit/test_schemas.py":             10,
    "unit/test_services.py":            16,
}

for f, minimum in min_tests.items():
    n = count_tests(f)
    check(f"min tests in {f}: have {n} >= {minimum}", n >= minimum,
          f"only {n} found, need {minimum}")


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print()
for r in RESULTS:
    print(r)

total = PASS + FAIL
print(f"\n{'─' * 60}")
print(f"  Phase 5 verification: {PASS}/{total} checks passed")
print(f"{'─' * 60}")

if FAIL:
    print(f"\n  ⚠  {FAIL} check(s) failed — see ✗ lines above.\n")
    sys.exit(1)
else:
    print("\n  🎉  All Phase 5 checks passed!\n")
    sys.exit(0)