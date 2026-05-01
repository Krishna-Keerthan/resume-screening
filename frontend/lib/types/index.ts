// ─── Enums ────────────────────────────────────────────────────────────────────
export type ApplicationStage =
  | "applied"
  | "reviewed"
  | "shortlisted"
  | "interviewing"
  | "offered"
  | "hired"
  | "rejected"
  | "withdrawn";

export type JobStatus = "draft" | "active" | "paused" | "closed";
export type JobType =
  | "full-time"
  | "part-time"
  | "contract"
  | "internship"
  | "freelance";
export type ParseStatus = "pending" | "success" | "failed";
export type ScoreLabel = "excellent" | "good" | "fair" | "weak";
export type CompanySize = "1-10" | "11-50" | "51-200" | "201-500" | "500+";
export type TipCategory = "skills" | "experience" | "education" | "format";
export type TipPriority = "high" | "medium" | "low";

// ─── Core Models ──────────────────────────────────────────────────────────────
export interface ImprovementTip {
  category: TipCategory;
  tip: string;
  priority: TipPriority;
}

export interface RoleSuggestion {
  title: string;
  reason: string;
  confidence: number;
  match_score?: number;
}

export interface AtsScore {
  id: string;
  resume_id: string;
  job_id: string;
  application_id?: string;
  final_score: number;
  score_label: ScoreLabel;
  semantic_score: number;
  keyword_score: number;
  experience_score: number;
  section_quality_score: number;
  semantic_available: boolean;
  matched_skills: string[];
  missing_skills: string[];
  extra_skills: string[];
  improvement_tips: ImprovementTip[];
  summary_text?: string;
  hiring_recommendation?: string;
  created_at?: string;
}

export interface Candidate {
  id: string;
  full_name: string;
  email: string;
  phone?: string;
  location?: string;
  headline?: string;
  linkedin_url?: string;
  github_url?: string;
  portfolio_url?: string;
  preferred_roles?: string[];
  preferred_locations?: string[];
  open_to_work: boolean;
  resumes?: Resume[];
  created_at: string;
  updated_at: string;
}

// Update Resume interface — add missing fields:
export interface Resume {
  id: string;
  candidate_id: string;
  file_name: string;          // ← was filename, now fixed
  file_size_bytes: number;    // ← computed from file_size_kb * 1024
  content_type: string | null;
  parse_status: ParseStatus;
  parse_error_msg?: string;
  skills: string[];
  education: EducationEntry[];
  experience: ExperienceEntry[];
  certifications: string[];
  projects: string[];
  total_experience_years: number;
  skill_count: number;
  summary_text?: string;
  resume_summary?: string;
  role_suggestions?: RoleSuggestion[];
  improvement_tips?: ImprovementTip[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}



// Add new types for improvements:
export interface SkillGap {
  skill: string;
  count: number;
  pct: number;
}

export interface WinRateInsight {
  skill: string;
  win_rate: number;
  wins: number;
  total: number;
}

export interface ImprovementPlanItem {
  rank: number;
  action: string;
  impact: "high" | "medium" | "low";
  effort: string;
}

export interface RewriteSuggestion {
  bullet: string;
  section: "experience" | "skills" | "projects";
  reasoning: string;
  for_skill: string;
}

// Update Application interface — add improvement_plan:
export interface Application {
  id: string;
  candidate_id: string;
  job_id: string;
  resume_id: string;
  stage: ApplicationStage;
  cover_letter?: string;
  recruiter_notes?: string;
  rejection_reason?: string;
  improvement_plan?: ImprovementPlanItem[];  // ← add
  applied_at: string;
  ats_score?: AtsScore;
  job?: Job;
  candidate?: Candidate;
  resume?: Resume;
}

export interface EducationEntry {
  institution?: string;
  degree?: string;
  field?: string;
  start_year?: number;
  end_year?: number;
  gpa?: number;
}

export interface ExperienceEntry {
  company?: string;
  title?: string;
  start_date?: string;
  end_date?: string;
  description?: string;
  years?: number;
}

export interface Recruiter {
  id: string;
  full_name: string;
  email: string;
  company_name: string;
  company_size?: CompanySize;
  industry?: string;
  phone?: string;
  website_url?: string;
  linkedin_url?: string;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  title: string;
  company: string;
  description: string;
  required_skills: string[];
  nice_to_have_skills: string[];
  responsibilities: string[];
  experience_years?: number;
  location: string;
  job_type: JobType;
  status: JobStatus;
  salary_min?: number;
  salary_max?: number;
  salary_currency: string;
  recruiter_id?: string;
  applicant_count?: number;
  quality_score?: number;
  completeness_score?: number;
  created_at: string;
  updated_at: string;
}

export interface Application {
  id: string;
  candidate_id: string;
  job_id: string;
  resume_id: string;
  stage: ApplicationStage;
  cover_letter?: string;
  recruiter_notes?: string;
  rejection_reason?: string;
  applied_at: string;
  ats_score?: AtsScore;
  job?: Job;
  candidate?: Candidate;
  resume?: Resume;
  improvement_plan?:ImprovementPlanItem[]
}


export interface AuthPayload {
  role: "candidate" | "recruiter";
  user_id: string;
  user: Candidate | Recruiter;
}

// ─── API Shapes ───────────────────────────────────────────────────────────────
export interface PaginationMeta {
  total: number;
  page: number;
  limit: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface ApiResponse<T> {
  success: boolean;
  message: string;
  data: T;
  meta?: PaginationMeta;
}

export interface ApiError {
  error_code: string;
  message: string;
  details?: Record<string, unknown>;
}

// ─── Analytics ────────────────────────────────────────────────────────────────
export interface RecruiterDashboard {
  total_jobs: number;
  active_jobs: number;
  total_applications: number;
  total_hired: number;
  avg_score: number;
  pipeline_funnel: Record<ApplicationStage, number>;
  top_jobs: { job_id: string; title: string; applicant_count: number; avg_score: number }[];
  score_distribution: { excellent: number; good: number; fair: number; weak: number };
  skills_demand: { skill: string; count: number }[];
}

export interface PipelineData {
  applied: number;
  reviewed: number;
  shortlisted: number;
  interviewing: number;
  offered: number;
  hired: number;
  rejected: number;
  withdrawn: number;
}

// ─── Scoring ──────────────────────────────────────────────────────────────────
export interface ScoreMatchResult extends AtsScore {
  saved: boolean;
  semantic_available: boolean;
}

export interface RankedCandidate {
  rank: number;
  candidate_id: string;
  candidate_name: string;
  resume_id: string;
  final_score: number;
  score_label: ScoreLabel;
  matched_skills: string[];
  missing_skills: string[];
  stage: ApplicationStage;
  application_id?: string;
}

export interface JobRecommendation {
  job_id: string;
  title: string;
  company: string;
  final_score: number;
  score_label: ScoreLabel;
  matched_skills: string[];
  location: string;
  job_type: JobType;
}

export interface JobEnhancement {
  job_id: string;
  quality_score: number;
  completeness_score: number;
  required_skills: string[];
  nice_to_have_skills: string[];
  responsibilities: string[];
  enhanced_description: string;
  suggestions: string[];
  llm_enhanced: boolean;
}

export interface SkillGapSingle {
  resume_id: string;
  job_id: string;
  resume_skills: string[];
  required_skills: string[];
  matched: string[];
  missing: string[];
  extra: string[];
  match_rate: number;
}

// ─── Auth ─────────────────────────────────────────────────────────────────────
export interface AuthState {
  role:           "candidate" | "recruiter" | null;
  userId:         string | null;
  userName:       string | null;
  accessToken:    string | null;
  setAuth:        (role: "candidate" | "recruiter", userId: string, userName: string, accessToken: string) => void;
  setAccessToken: (token: string) => void;
  logout:         () => void;
}

// ─── Health ───────────────────────────────────────────────────────────────────
export interface HealthServices {
  database: { available: boolean; description: string };
  embedding: { available: boolean; description: string };
  groq: { available: boolean; description: string };
  all_optional_services_available: boolean;
}

// ─── Forms ────────────────────────────────────────────────────────────────────
export interface CreateCandidateForm {
  full_name:            string;
  email:                string;
  password:             string;
  phone?:               string;
  location?:            string;
  headline?:            string;
  open_to_work?:        boolean;
  preferred_roles?:     string[];
  preferred_locations?: string[];
  linkedin_url?:        string;
  github_url?:          string;
  portfolio_url?:       string;
}

export interface CreateRecruiterForm {
  full_name:     string;
  email:         string;
  password:      string;
  company_name:  string;
  company_size?: CompanySize;
  industry?:     string;
  phone?:        string;
  website_url?:  string;
  linkedin_url?: string;
}

export interface CreateJobForm {
  title: string;
  company: string;
  description: string;
  required_skills?: string[];
  nice_to_have_skills?: string[];
  experience_years?: number;
  location?: string;
  job_type?: JobType;
  status?: JobStatus;
  salary_min?: number;
  salary_max?: number;
  salary_currency?: string;
  recruiter_id?: string;
}

export interface StageUpdateForm {
  stage: ApplicationStage;
  recruiter_notes?: string;
  rejection_reason?: string;
}
