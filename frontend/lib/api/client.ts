import axios, { AxiosInstance } from "axios";
import {
  ApiResponse, Candidate, Recruiter, Job, Resume,
  Application, AtsScore, ScoreMatchResult, RankedCandidate, JobRecommendation,
  JobEnhancement, RecruiterDashboard, PipelineData,
  CreateCandidateForm, CreateRecruiterForm, CreateJobForm, StageUpdateForm,
  SkillGapSingle, 
} from "@/lib/types";

// ─── Auth response shape ───────────────────────────────────────────────────────
// Matches backend _auth_response():
// { success, message, data: { access_token, token_type, expires_in, role, user } }
export interface AuthPayload {
  access_token: string;
  token_type:   "Bearer";
  expires_in:   number;        // seconds (900 = 15 min)
  role:         "candidate" | "recruiter";
  user:         Candidate | Recruiter;
}

// /auth/me returns a slightly different shape (no token fields)
export interface MePayload {
  role: "candidate" | "recruiter";
  user: Candidate | Recruiter;
}

// ─── Error class ──────────────────────────────────────────────────────────────
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status?: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const AUTH_EXPIRY_CODES = new Set([
  "REFRESH_EXPIRED",
  "MISSING_TOKEN",   // refresh cookie missing
  "TOKEN_REUSED",    // replay detected
  "INVALID_TOKEN",   // generic frontend variant
  "TOKEN_INVALID",   // backend variant used by refresh endpoint
]);

// ─── Friendly error messages ──────────────────────────────────────────────────
const ERROR_MESSAGES: Record<string, string> = {
  // Auth
  INVALID_CREDENTIALS:       "Invalid email or password.",
  MISSING_TOKEN:             "Your session has expired. Please log in again.",
  // This message is shown when /auth/refresh returns MISSING_TOKEN (no refresh cookie).
  // If a protected endpoint returns MISSING_TOKEN (missing Bearer header),
  // the Axios interceptor silently refreshes the token and this message
  // is never shown to the user.

  TOKEN_EXPIRED:             "Your session has expired. Please log in again.",
  REFRESH_EXPIRED:           "Your session has expired. Please log in again.",
  INVALID_TOKEN:             "Authentication error. Please log in again.",
  TOKEN_REUSED:              "Security alert: your session was invalidated. Please log in again.",
  FORBIDDEN:                 "You don't have permission to do that.",
  USER_NOT_FOUND:            "No account found for that email.",
  // Registration
  CANDIDATE_EMAIL_CONFLICT:  "This email is already registered.",
  RECRUITER_EMAIL_CONFLICT:  "This email is already registered.",
  // Application
  DUPLICATE_APPLICATION:     "You have already applied to this job.",
  JOB_NOT_ACTIVE:            "This job is no longer accepting applications.",
  RESUME_OWNERSHIP_MISMATCH: "Please select your own resume.",
  CANNOT_WITHDRAW:           "Cannot withdraw a finalized application.",
  // File
  UNSUPPORTED_FILE_TYPE:     "Only PDF and DOCX files are accepted.",
  NO_FILE_UPLOADED:          "No file included in the request.",
  // Scoring
  RESUME_NOT_PARSED:         "Resume still processing — please try again shortly.",
  SCORING_FAILED:            "Scoring failed — please try again.",
  // Generic
  MISSING_PARAM:             "A required parameter is missing.",
  VALIDATION_ERROR:          "Please check the highlighted fields.",
  NETWORK_ERROR:             "Cannot reach server. Is the backend running?",
  // Resources
  CANDIDATE_NOT_FOUND:       "Candidate not found.",
  RECRUITER_NOT_FOUND:       "Recruiter not found.",
  JOB_NOT_FOUND:             "Job not found.",
  RESUME_NOT_FOUND:          "Resume not found.",
};

export function getFriendlyError(err: unknown): string {
  if (err instanceof ApiError) {
    return ERROR_MESSAGES[err.code] ?? err.message;
  }
  return "Something went wrong. Please try again.";
}

// ─── Query key factory ────────────────────────────────────────────────────────
export const queryKeys = {
  health:                    () => ["health"] as const,
  healthServices:            () => ["health", "services"] as const,
  authMe:                    (role: string, userId: string) => ["auth", "me", role, userId] as const,
  candidates:                (p?: number, l?: number, q?: string) => ["candidates", p, l, q] as const,
  candidate:                 (id: string) => ["candidate", id] as const,
  candidateResumes:          (id: string) => ["candidate", id, "resumes"] as const,
  candidateRecommendations:  (id: string) => ["candidate", id, "recommendations"] as const,
  candidateSkillGaps:    (id: string) => ["candidate", id, "skill-gaps"] as const,
  candidateWinRate:      (id: string) => ["candidate", id, "win-rate"] as const,
  applicationAiSummary:  (id: string) => ["application", id, "ai-summary"] as const,
  recruiters:                (p?: number, l?: number, q?: string) => ["recruiters", p, l, q] as const,
  recruiter:                 (id: string) => ["recruiter", id] as const,
  recruiterJobs:             (id: string, status?: string) => ["recruiter", id, "jobs", status] as const,
  recruiterAnalytics:        (id: string) => ["recruiter", id, "analytics"] as const,
  recruiterPipeline:         (id: string) => ["recruiter", id, "pipeline"] as const,
  jobs:                      (p?: number, l?: number, filters?: Record<string, string>) => ["jobs", p, l, filters] as const,
  job:                       (id: string) => ["job", id] as const,
  jobCandidates:             (id: string, p?: number) => ["job", id, "candidates", p] as const,
  jobSkillGaps:              (id: string) => ["job", id, "skill-gaps"] as const,
  jobPerformance:            (id: string) => ["job", id, "performance"] as const,
  resumes:                   (p?: number, l?: number) => ["resumes", p, l] as const,
  resume:                    (id: string) => ["resume", id] as const,
  resumeSummary:        (id: string) => ["resume", id, "summary"] as const,
  rewriteSuggestions:   (resumeId: string, jobId: string) => ["rewrite", resumeId, jobId] as const,
  scorePreview:              (resumeId: string, jobId: string) => ["score-preview", resumeId, jobId] as const,
  applications:              (filters?: Record<string, string>) => ["applications", filters] as const,
  application:               (id: string) => ["application", id] as const,
  scores:                    (filters?: Record<string, string>) => ["scores", filters] as const,
  analyticsBoard:            (recruiterId: string) => ["analytics", recruiterId, "dashboard"] as const,
  analyticsPipeline:         (recruiterId: string) => ["analytics", recruiterId, "pipeline"] as const,
  analyticsScoreDist:        (recruiterId: string) => ["analytics", recruiterId, "score-dist"] as const,
  analyticsSkillsDemand:     (recruiterId: string) => ["analytics", recruiterId, "skills"] as const,
  analyticsTopJobs:          (recruiterId: string) => ["analytics", recruiterId, "top-jobs"] as const,
};

// ─── Token storage (module-level memory — survives re-renders, cleared on reload) ─

// ⚠️  MODULE-LEVEL STATE — CLIENT SIDE ONLY
// _accessToken and _refreshing are intentionally module-scoped for performance
// (avoids React context overhead for every request).
// This file MUST remain a client-only module ("use client" or imported only
// from client components). If ever used server-side, these vars would be
// shared across all user requests — a serious security leak.
// See: https://nextjs.org/docs/app/building-your-application/rendering/composition-patterns


let _accessToken: string | null = null;

export function setClientToken(token: string | null) {
  _accessToken = token;
}
export function getClientToken(): string | null {
  return _accessToken;
}

// ─── Axios instance ───────────────────────────────────────────────────────────
let _refreshing: Promise<string | null> | null = null;

export function resetClientState() {
  _accessToken = null;
  _refreshing  = null; 
}

const API_BASE_URL =
  typeof window === "undefined"
    ? process.env.INTERNAL_API_URL
    : process.env.NEXT_PUBLIC_API_URL; 

if (!API_BASE_URL) {
  throw new Error("API base URL is not configured");
}

const createApiClient = (): AxiosInstance => {
  const client = axios.create({
    baseURL: `${API_BASE_URL}/api/v1`,
    // typeof window === "undefined"
    //   ? (process.env.INTERNAL_API_URL || "http://ats_flask:5000/api/v1")
    //   : (process.env.NEXT_PUBLIC_API_URL || "/api/v1"),
    headers:          { "Content-Type": "application/json" },
    timeout:          120_000,
    withCredentials:  true,   // ← REQUIRED: sends HttpOnly refresh_token cookie
  });

  // ── Request interceptor: attach Bearer token ───────────────────────────────
  client.interceptors.request.use((config) => {
    const token = _accessToken;
    if (token) {
      config.headers["Authorization"] = `Bearer ${token}`;
    }
    return config;
  });

  // ── Response interceptor: handle errors + silent token refresh ────────────
  client.interceptors.response.use(
    (res) => {
      // Backend returned 2xx but success: false (shouldn't happen, but guard it)
      if (res.data?.success === false && res.data?.error) {
        throw new ApiError(
          res.data.error.error_code,
          res.data.error.message,
          res.status
        );
      }
      return res;
    },
    async (err) => {
      const data   = err.response?.data;
      const status = err.response?.status;

      // Parse structured error
      const code: string =
        data?.error?.error_code ?? data?.error_code ?? "UNKNOWN";
      const message: string =
        data?.error?.message ?? data?.message ?? err.message ?? "Unknown error";

      // ── Silent refresh on 401 TOKEN_EXPIRED ────────────────────────────────
      // Only attempt once per failed request. Don't retry refresh calls themselves.
      const isRefreshEndpoint = err.config?.url?.includes("/auth/refresh");

      // MISSING_TOKEN has two meanings depending on endpoint:
      //
      // 1. Protected endpoints → access token missing in Authorization header
      //    Safe to attempt silent refresh.
      //
      // 2. /auth/refresh endpoint → refresh cookie missing
      //    Means session is fully expired → must logout.
      //
      // Because we exclude /auth/* endpoints below, this block only runs
      // for case (1), so silent refresh is safe.
      if (
        status === 401 &&
        (code === "TOKEN_EXPIRED" || code === "MISSING_TOKEN") &&
        !isRefreshEndpoint &&
        !err.config?._retried
      ) {
        // Deduplicate concurrent refresh calls
        if (!_refreshing) {
          _refreshing = (async () => {
              try {
                const res = await client.post<ApiResponse<AuthPayload>>(
                  "/auth/refresh",
                  {},
                  { withCredentials: true, headers: { "Content-Type": "application/json" } }
                );
                const newToken = res.data.data.access_token;
                _accessToken = newToken;
                return newToken;
              } catch (refreshErr) {
                _accessToken = null;
                
                // Only redirect on definitive session expiry — not on race-condition 401s.
                // If AuthProvider is already handling the redirect, don't double-redirect.
                const code = refreshErr instanceof ApiError ? refreshErr.code : "";
                const hardLogoutCodes = new Set([
                  "REFRESH_EXPIRED", "TOKEN_REUSED", "TOKEN_INVALID", "INVALID_TOKEN"
                ]);
                
                if (hardLogoutCodes.has(code) && typeof window !== "undefined") {
                  window.location.href = "/login";
                }
                // MISSING_TOKEN on a race condition — don't redirect, just return null.
                // The original request will fail and AuthProvider handles the UI state.
                
                return null;
              } finally {
                _refreshing = null;
              }
            })();
        }

        const newToken = await _refreshing;
        if (newToken) {
          // Retry original request with new token
          err.config.headers["Authorization"] = `Bearer ${newToken}`;
          err.config._retried = true;
          return client(err.config);
        }
      }

      // TOKEN_REUSED means all sessions were killed — force logout immediately
      if (code === "TOKEN_REUSED") {
        _accessToken = null;
        if (typeof window !== "undefined") {
          window.location.href = "/login";
        }
      }

      // Map error codes we already handle gracefully
      if (status !== undefined) {
        throw new ApiError(code, message, status);
      }

      if (!err.response) {
        throw new ApiError("NETWORK_ERROR", "Cannot reach server.", 0);
      }

      throw new ApiError(code, message, status);
    }
  );

  return client;
};

export const apiClient = createApiClient();

// ─── Helpers ──────────────────────────────────────────────────────────────────
async function get<T>(url: string, params?: Record<string, unknown>): Promise<ApiResponse<T>> {
  const res = await apiClient.get<ApiResponse<T>>(url, { params });
  return res.data;
}
async function post<T>(url: string, body?: unknown): Promise<ApiResponse<T>> {
  const res = await apiClient.post<ApiResponse<T>>(url, body);
  return res.data;
}
async function patch<T>(url: string, body?: unknown): Promise<ApiResponse<T>> {
  const res = await apiClient.patch<ApiResponse<T>>(url, body);
  return res.data;
}
async function del<T>(url: string): Promise<ApiResponse<T>> {
  const res = await apiClient.delete<ApiResponse<T>>(url);
  return res.data;
}

// ─── API Functions ────────────────────────────────────────────────────────────
export const api = {

  // ── Auth ──────────────────────────────────────────────────────────────────
  // POST /auth/login  Body: { email, password, role }
  // Returns: AuthPayload (access_token + user)
  // Refresh token arrives as HttpOnly cookie automatically
  authLogin: (body: {
    email:    string;
    password: string;
    role:     "candidate" | "recruiter";
  }) => post<AuthPayload>("/auth/login", body),

  // POST /auth/register/candidate  Body: { full_name, email, password, ...optional }
  authRegisterCandidate: (body: CreateCandidateForm) =>
    post<AuthPayload>("/auth/register/candidate", body),

  // POST /auth/register/recruiter  Body: { full_name, email, password, company_name, ...optional }
  authRegisterRecruiter: (body: CreateRecruiterForm) =>
    post<AuthPayload>("/auth/register/recruiter", body),

  // POST /auth/refresh  (no body — reads HttpOnly cookie)
  // Returns new access_token; sets new refresh cookie
  authRefresh: () => post<AuthPayload>("/auth/refresh"),

  // GET /auth/me  (requires Bearer token)
  // Returns current user profile based on token identity
  authMe: () => get<MePayload>("/auth/me"),

  // POST /auth/logout  (requires Bearer token + cookie)
  // Revokes current refresh token, clears cookie
  authLogout: () => post<{ message: string }>("/auth/logout"),

  // POST /auth/logout-all  (requires Bearer token)
  // Revokes ALL sessions for this user
  authLogoutAll: () => post<{ message: string; sessions_revoked: number }>("/auth/logout-all"),

  // POST /auth/change-password  Body: { current_password, new_password }
  authChangePassword: (body: { current_password: string; new_password: string }) =>
    post<{ message: string }>("/auth/change-password", body),

  // ── Health ────────────────────────────────────────────────────────────────
  getHealth:         () => get<{ status: string; uptime_seconds: number }>("/health"),
  getHealthReady:    () => get<{ status: string }>("/health/ready"),
  getHealthServices: () =>
    get<{
      services: {
        database:  { available: boolean; description: string };
        embedding: { available: boolean; description: string };
        groq:      { available: boolean; description: string };
      };
      all_optional_services_available: boolean;
    }>("/health/services"),

  // ── Candidates ────────────────────────────────────────────────────────────
  listCandidates: (page = 1, limit = 20, params?: Record<string, unknown>) =>
    get<Candidate[]>("/candidates", { page, limit, ...params }),
  getCandidate: (id: string) => get<Candidate>(`/candidates/${id}`),
  // NOTE: createCandidate is removed — use api.authRegisterCandidate instead
  updateCandidate: (id: string, body: Partial<CreateCandidateForm>) =>
    patch<Candidate>(`/candidates/${id}`, body),
  deleteCandidate: (id: string) => del(`/candidates/${id}`),
  getCandidateResumes: (id: string, page = 1, limit = 20) =>
    get<Resume[]>(`/candidates/${id}/resumes`, { page, limit }),
  uploadResume: async (candidateId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await apiClient.post<ApiResponse<Resume>>(
      `/candidates/${candidateId}/resumes`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } }
    );
    return res.data;
  },
  getCandidateRecommendations: (id: string, params?: Record<string, unknown>) =>
    post<{ total: number; recommendations: JobRecommendation[] }>(
      `/candidates/${id}/recommendations`, params
    ),

  getCandidateSkillGaps: (candidateId: string) =>
  get<{
    skill_gaps: { skill: string; count: number; pct: number }[];
    total_applications_scored: number;
  }>(`/candidates/${candidateId}/skill-gaps`),

  getCandidateWinRateInsights: (candidateId: string) =>
    get<{
      top_performing_skills: {
        skill: string;
        win_rate: number;
        wins: number;
        total: number;
      }[];
      total_applications: number;
    }>(`/candidates/${candidateId}/win-rate-insights`),

  // ── Recruiters ────────────────────────────────────────────────────────────
  listRecruiters: (page = 1, limit = 20, params?: Record<string, unknown>) =>
    get<Recruiter[]>("/recruiters", { page, limit, ...params }),
  getRecruiter: (id: string) => get<Recruiter>(`/recruiters/${id}`),
  // NOTE: createRecruiter is removed — use api.authRegisterRecruiter instead
  updateRecruiter: (id: string, body: Partial<CreateRecruiterForm>) =>
    patch<Recruiter>(`/recruiters/${id}`, body),
  deleteRecruiter: (id: string) => del(`/recruiters/${id}`),
  getRecruiterJobs: (id: string, params?: Record<string, unknown>) =>
    get<Job[]>(`/recruiters/${id}/jobs`, params),
  getRecruiterAnalytics: (id: string) =>
    get<RecruiterDashboard>(`/recruiters/${id}/analytics`),
  getRecruiterPipeline: (id: string) =>
    get<PipelineData>(`/recruiters/${id}/pipeline`),

  // ── Jobs ──────────────────────────────────────────────────────────────────
  listJobs: (page = 1, limit = 20, params?: Record<string, unknown>) =>
    get<Job[]>("/jobs", { page, limit, ...params }),
  getJob: (id: string) => get<Job>(`/jobs/${id}`),
  createJob: (body: CreateJobForm) => post<Job>("/jobs", body),
  updateJob: (id: string, body: Partial<CreateJobForm>) =>
    patch<Job>(`/jobs/${id}`, body),
  deleteJob: (id: string) => del(`/jobs/${id}`),
  enhanceJob: (id: string, useLlm = true) =>
    post<JobEnhancement>(`/jobs/${id}/enhance`, { use_llm: useLlm }),
  getJobCandidates: (id: string, params?: Record<string, unknown>) =>
    get<RankedCandidate[]>(`/jobs/${id}/candidates`, params),
  getJobSkillGaps: (id: string) =>
    get<{
      top_missing_skills: { skill: string; count: number }[];
      top_matched_skills: { skill: string; count: number }[];
    }>(`/jobs/${id}/skill-gaps`),
  getJobPerformance: (id: string) =>
    get<{
      applicant_count:    number;
      avg_score:          number;
      stage_breakdown:    Record<string, number>;
      top_skills_matched: string[];
    }>(`/jobs/${id}/performance`),

  // ── Resumes ───────────────────────────────────────────────────────────────
  listResumes: (page = 1, limit = 20, params?: Record<string, unknown>) =>
    get<Resume[]>("/resumes", { page, limit, ...params }),
  getResume: (id: string) => get<Resume>(`/resumes/${id}`),
  deleteResume: (id: string) => del(`/resumes/${id}`),
  analyzeResume: (id: string, forceRefresh = false) =>
    post<Resume>(`/resumes/${id}/analyze`, { force_refresh: forceRefresh }),
  getScorePreview: (resumeId: string, jobId: string) =>
    get<ScoreMatchResult>(`/resumes/${resumeId}/score-preview`, { job_id: jobId }),
  generateResumeSummary: (resumeId: string, targetRole?: string) =>
  post<{ summary: string; resume: Resume }>(
    `/resumes/${resumeId}/generate-summary`,
    { target_role: targetRole ?? "" }
  ),
  getRewriteSuggestions: (resumeId: string, jobId: string) =>
    post<{
      missing_skills: string[];
      suggestions: {
        bullet: string;
        section: string;
        reasoning: string;
        for_skill: string;
      }[];
      job_title: string;
    }>(`/resumes/${resumeId}/rewrite-suggestions`, { job_id: jobId }),

  setActiveResume: (resumeId: string) =>
    patch<Resume>(`/resumes/${resumeId}/set-active`),

  // ── Applications ──────────────────────────────────────────────────────────
  listApplications: (params?: Record<string, unknown>) =>
    get<Application[]>("/applications", params),
  getApplication: (id: string) => get<Application>(`/applications/${id}`),
  createApplication: (body: {
    candidate_id: string; job_id: string; resume_id: string; cover_letter?: string;
  }) => post<Application>("/applications", body),
  updateApplicationStage: (id: string, body: StageUpdateForm) =>
    patch<Application>(`/applications/${id}/stage`, body),
  withdrawApplication: (id: string) => del<Application>(`/applications/${id}`),
  scoreApplication: (id: string, useLlm = true) =>
    post<AtsScore>(`/applications/${id}/score`, { use_llm: useLlm }),
  getApplicationAiSummary: (applicationId: string) =>
    get<{ summary: string; recommendation: string }>(
      `/applications/${applicationId}/ai-summary`
    ),

  // ── Scoring ───────────────────────────────────────────────────────────────
  scoreMatch: (resumeId: string, jobId: string, saveResult = true) =>
    post<ScoreMatchResult>("/scores/match", {
      resume_id: resumeId, job_id: jobId, save_result: saveResult,
    }),
  rankCandidates: (jobId: string, params?: Record<string, unknown>) =>
    post<{
      job_id:      string;
      total:       number;
      score_stats: Record<string, number>;
      candidates:  RankedCandidate[];
    }>("/scores/rank-candidates", { job_id: jobId, ...params }),
  jobRecommendations: (resumeId: string, params?: Record<string, unknown>) =>
    post<{
      resume_id:       string;
      total:           number;
      recommendations: JobRecommendation[];
    }>("/scores/job-recommendations", { resume_id: resumeId, ...params }),
  skillGap: (resumeId: string, jobId?: string) =>
    post<SkillGapSingle>("/scores/skill-gap", {
      resume_id: resumeId, ...(jobId ? { job_id: jobId } : {}),
    }),
  listScores: (params?: Record<string, unknown>) => get<AtsScore[]>("/scores", params),
  getScore: (id: string) => get<AtsScore>(`/scores/${id}`),

  // ── Analytics ─────────────────────────────────────────────────────────────
  getAnalyticsDashboard: (recruiterId: string) =>
    get<RecruiterDashboard>("/analytics/dashboard", { recruiter_id: recruiterId }),
  getAnalyticsPipeline: (recruiterId: string) =>
    get<PipelineData>("/analytics/pipeline", { recruiter_id: recruiterId }),
  getAnalyticsScoreDistribution: (recruiterId: string) =>
    get<{ excellent: number; good: number; fair: number; weak: number }>(
      "/analytics/score-distribution", { recruiter_id: recruiterId }
    ),
  getAnalyticsSkillsDemand: (recruiterId: string, topN = 15) =>
    get<{ skills: { skill: string; count: number }[] }>(
      "/analytics/skills-demand", { recruiter_id: recruiterId, top_n: topN }
    ),
  getAnalyticsTopJobs: (recruiterId: string, topN = 5) =>
    get<{ jobs: { job_id: string; title: string; applicant_count: number; avg_score: number }[] }>(
      "/analytics/top-jobs", { recruiter_id: recruiterId, top_n: topN }
    ),

}
