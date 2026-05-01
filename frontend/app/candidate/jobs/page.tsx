"use client";
import { useCallback, useState, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api, queryKeys, getFriendlyError } from "@/lib/api/client";
import { useAuthStore } from "@/lib/store/authStore";
import { CardSkeleton, SkillBadge, ScoreBadge, EmptyState, PaginationBar } from "@/components/shared";
import { AtsScoreCard } from "@/components/shared/AtsScoreCard";
import { formatSalary, formatExperience, formatRelativeDate } from "@/lib/utils/formatters";
import { Search, MapPin, Briefcase, Clock, DollarSign, X, Loader2, Eye, AlertCircle ,CheckCircle2, FileText, Zap  } from "lucide-react";
import { toast } from "sonner";
import { Job, ScoreMatchResult, Resume, JobRecommendation } from "@/lib/types";
import { getClientToken } from "@/lib/api/client";
import Link from "next/link";
import Portal from '@/components/ui/Portal'
const JOB_TYPES = ["full-time", "part-time", "contract", "internship", "freelance"];

export default function JobsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { userId } = useAuthStore();

  const page = Number(searchParams.get("page") ?? 1);
  const search = searchParams.get("search") ?? "";
  const jobType = searchParams.get("job_type") ?? "";
  const location = searchParams.get("location") ?? "";

  const [searchInput, setSearchInput] = useState(search);
  const [previewScores, setPreviewScores] = useState<Record<string, ScoreMatchResult>>({});
  const [loadingPreview, setLoadingPreview] = useState<string | null>(null);

  // State for picker
  const [pickerJobId, setPickerJobId] = useState<string | null>(null);
  const [selectedResumeId, setSelectedResumeId] = useState<string>("");

  const [postApplyRecs, setPostApplyRecs] = useState<JobRecommendation[]>([]);
  const [appliedJobId, setAppliedJobId] = useState<string | null>(null);

  const [rewriteSuggestions, setRewriteSuggestions] = useState<Record<string, any>>({});
  const [loadingRewrites, setLoadingRewrites] = useState<string | null>(null);

  

  const [autoScoring, setAutoScoring] = useState(false);

  

  const setFilter = useCallback((key: string, value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    value ? params.set(key, value) : params.delete(key);
    params.delete("page");
    router.push(`?${params}`);
  }, [searchParams, router]);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.jobs(page, 20, { search, job_type: jobType, location }),
    queryFn: () => {
      const params: Record<string, string> = {};

      if (search) params.search = search;
      if (jobType) params.job_type = jobType;
      if (location) params.location = location;

      return api.listJobs(page, 20, params);
    },
  });

  // Get active resume for previews
  const { data: resumesData } = useQuery({
  queryKey: queryKeys.candidateResumes(userId!),
  queryFn: () => api.getCandidateResumes(userId!),
  enabled: !!userId && !!getClientToken(), 
    });
  const ownResumes = (resumesData?.data ?? []).filter(
    (r: Resume) => r.parse_status === "success"
  );
  const activeResume = ownResumes.find((r: Resume) => r.is_active) ?? ownResumes[0];

  const jobs: Job[] = data?.data ?? [];

  const canApply = activeResume?.parse_status === "success";
  
  
  const handleApplyClick = (job: Job) => {
    if (ownResumes.length === 0) {
      toast.error("Upload and parse a resume before applying.");
      return;
    }
    // Pre-select active resume
    setSelectedResumeId(activeResume?.id ?? ownResumes[0]?.id ?? "");
    setPickerJobId(job.id);
  };

  const applyMutation = useMutation({
    mutationFn: ({ jobId, resumeId }: { jobId: string; resumeId: string }) =>
      api.createApplication({ candidate_id: userId!, job_id: jobId, resume_id: resumeId }),
    onSuccess: async (_, { jobId }) => {
      toast.success("Application submitted!");
      setPickerJobId(null);
      setAppliedJobId(jobId);
      setSelectedResumeId("");

      // Fetch similar job recommendations
      if (activeResume?.id) {
        try {
          const recs = await api.jobRecommendations(activeResume.id, { top_n: 3 });
          const recJobs = (recs.data?.recommendations ?? [])
            .filter((r: JobRecommendation) => r.job_id !== jobId)
            .slice(0, 3);
          setPostApplyRecs(recJobs);
        } catch { /* silent */ }
      }
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  const handlePreview = async (job: Job) => {
    if (!activeResume) { toast.error("Upload a resume first to preview your match score."); return; }
    if (previewScores[job.id]) return;
    setLoadingPreview(job.id);
    try {
      const res = await api.getScorePreview(activeResume.id, job.id);
      setPreviewScores((p) => ({ ...p, [job.id]: res.data }));
    } catch { toast.error("Could not load preview."); }
    finally { setLoadingPreview(null); }
  };

  const handleGetRewrites = async (job: Job) => {
    if (!activeResume?.id || rewriteSuggestions[job.id]) return;
    setLoadingRewrites(job.id);
    try {
      const res = await api.getRewriteSuggestions(activeResume.id, job.id);
      setRewriteSuggestions((prev) => ({ ...prev, [job.id]: res.data }));
    } catch { toast.error("Could not load suggestions."); }
    finally { setLoadingRewrites(null); }
  };


  useEffect(() => {
    if (!activeResume?.id || jobs.length === 0 || autoScoring) return;
    if (activeResume.parse_status !== "success") return;

    const unscored = jobs.filter((j) => !previewScores[j.id]);
    if (unscored.length === 0) return;

    setAutoScoring(true);
    Promise.allSettled(
      unscored.map((job) =>
        api.getScorePreview(activeResume.id, job.id)
          .then((res) => ({ jobId: job.id, score: res.data }))
      )
    ).then((results) => {
      const newScores: Record<string, ScoreMatchResult> = {};
      results.forEach((result) => {
        if (result.status === "fulfilled") {
          newScores[result.value.jobId] = result.value.score;
        }
      });
      setPreviewScores((prev) => ({ ...prev, ...newScores }));
      setAutoScoring(false);
    });
  }, [jobs, activeResume?.id]);
  



  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-bold text-text-primary mb-1">Job Board</h1>
        <p className="text-text-secondary">Find your next opportunity</p>
      </div>

      {/* Filters */}
      <div className="card p-4 mb-6 flex flex-wrap gap-3">
        <div className="flex-1 min-w-48 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input
            className="input pl-9"
            placeholder="Search jobs, companies..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
        </div>
        <div className="relative">
          <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input
            className="input pl-9 w-44"
            placeholder="Location..."
            value={location}
            onChange={(e) => setFilter("location", e.target.value)}
          />
        </div>
        <select
          className="input w-40"
          value={jobType}
          onChange={(e) => setFilter("job_type", e.target.value)}
        >
          <option value="">All types</option>
          {JOB_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        {(search || jobType || location) && (
          <button onClick={() => { setSearchInput(""); router.push("?"); }} className="btn-ghost flex items-center gap-1 text-text-muted">
            <X className="w-4 h-4" /> Clear
          </button>
        )}
      </div>

      {/* Active resume indicator */}
      <div className="mb-6">
        <ActiveResumeIndicator resume={activeResume} />
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[1,2,3,4].map((i) => <CardSkeleton key={i} />)}
        </div>
      ) : jobs.length === 0 ? (
        <EmptyState icon={<Briefcase className="w-7 h-7" />} title="No jobs found" description="Try adjusting your filters." />
      ) : (
        <div className="space-y-4">
          {jobs.map((job) => (
            <div key={job.id} className="card-hover overflow-hidden">
              <div className="p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start gap-3">
                      <div className="w-10 h-10 rounded-xl bg-charcoal-700 flex items-center justify-center flex-shrink-0">
                        <Briefcase className="w-5 h-5 text-text-muted" />
                      </div>
                      <div>
                      <Link href={`/candidate/jobs/${job.id}`}>
                        <h3 className="font-display font-semibold text-text-primary hover:text-electric-400 transition-colors cursor-pointer">
                          {job.title}
                        </h3>
                      </Link>
                      <p className="text-text-muted text-sm">{job.company}</p>
                    </div>
                    </div>

                    <div className="flex flex-wrap gap-3 mt-3 text-xs text-text-muted">
                      <span className="flex items-center gap-1"><MapPin className="w-3 h-3" />{job.location}</span>
                      <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{job.job_type}</span>
                      {(job.salary_min || job.salary_max) && (
                        <span className="flex items-center gap-1"><DollarSign className="w-3 h-3" />{formatSalary(job.salary_min, job.salary_max, job.salary_currency)}</span>
                      )}
                      {job.experience_years && (
                        <span className="flex items-center gap-1"><Briefcase className="w-3 h-3" />{formatExperience(job.experience_years)}</span>
                      )}
                    </div>

                    <div className="flex flex-wrap gap-1 mt-3">
                      <div className="text-xs text-text-muted">{job.applicant_count ?? 0} applicants</div>
                      {job.required_skills.slice(0, 4).map((s, i) => <SkillBadge key={i} skill={s} />)}
                      {job.required_skills.length > 4 && (
                        <span className="text-xs text-text-muted self-center">+{job.required_skills.length - 4}</span>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-col items-end gap-2 flex-shrink-0">
                    {previewScores[job.id] && (
                      <ScoreBadge score={previewScores[job.id].final_score} label={previewScores[job.id].score_label} />
                    )}
                    <div className="flex gap-2">
                      <button
                        onClick={() => handlePreview(job)}
                        disabled={loadingPreview === job.id}
                        className="btn-secondary text-xs py-1.5 px-3 flex items-center gap-1.5"
                      >
                        {loadingPreview === job.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Eye className="w-3 h-3" />}
                        Preview Match
                      </button>
                      <button
                        onClick={() => handleApplyClick(job)}
                        disabled={applyMutation.isPending}
                        title={activeResume ? `Apply with: ${activeResume.file_name}` : "Upload a resume to apply"}
                        className="btn-primary text-xs py-1.5 px-3 flex items-center gap-1.5"
                      >
                        {applyMutation.isPending && pickerJobId === job.id ? <Loader2 className="w-3 h-3 animate-spin" /> : "Apply"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>


              {previewScores[job.id] && (
              <div className="border-t border-white/[0.06] bg-charcoal-900/50 p-4 space-y-3">
                <AtsScoreCard score={previewScores[job.id]} mode="preview" />

                {/* Rewrite Suggestions */}
                {!rewriteSuggestions[job.id] ? (
                  <button
                    onClick={() => handleGetRewrites(job)}
                    disabled={loadingRewrites === job.id}
                    className="btn-ghost text-xs flex items-center gap-1.5 text-electric-400"
                  >
                    {loadingRewrites === job.id
                      ? <Loader2 className="w-3 h-3 animate-spin" />
                      : <Zap className="w-3 h-3" />
                    }
                    Get AI Rewrite Suggestions
                  </button>
                ) : (
                  <div className="space-y-2">
                    <p className="text-xs font-semibold text-text-muted uppercase tracking-wider">
                      Resume Improvement Suggestions
                    </p>
                    {rewriteSuggestions[job.id].suggestions?.map((s: any, i: number) => (
                      <div key={i} className="p-3 rounded-lg bg-charcoal-800 border border-white/[0.05] space-y-1">
                        <div className="flex items-start gap-2">
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-electric-500/15 text-electric-400 flex-shrink-0">
                            {s.for_skill}
                          </span>
                          <p className="text-xs text-text-secondary leading-relaxed">{s.bullet}</p>
                        </div>
                        <button
                          onClick={() => { navigator.clipboard.writeText(s.bullet); toast.success("Copied!"); }}
                          className="text-[10px] text-text-muted hover:text-electric-400 transition-colors"
                        >
                          Copy bullet →
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            </div>
          ))}
        </div>
      )}


      {pickerJobId && (
          <Portal>
            <div
              className="fixed inset-0 flex items-center justify-center z-[100]"
              onClick={() => setPickerJobId(null)}
            >
              <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
              <div
                className="relative w-full max-w-md mx-4 bg-charcoal-900 border border-white/[0.08] rounded-2xl shadow-2xl p-6 space-y-4"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="flex items-center justify-between">
                  <h2 className="font-display font-semibold text-text-primary">Select Resume to Apply With</h2>
                  <button onClick={() => setPickerJobId(null)} className="p-2 rounded-lg hover:bg-charcoal-700">
                    <X className="w-4 h-4 text-text-muted" />
                  </button>
                </div>

                <p className="text-text-muted text-xs">
                  Choose which of your resumes to submit with this application.
                </p>

                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {ownResumes.map((resume: Resume) => (
                    <button
                      key={resume.id}
                      onClick={() => setSelectedResumeId(resume.id)}
                      className={`w-full text-left p-3 rounded-xl border transition-all ${
                        selectedResumeId === resume.id
                          ? "border-electric-500/50 bg-electric-500/10"
                          : "border-white/[0.07] bg-charcoal-800 hover:border-white/[0.15]"
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                          selectedResumeId === resume.id ? "bg-electric-500/20" : "bg-charcoal-700"
                        }`}>
                          <FileText className={`w-4 h-4 ${
                            selectedResumeId === resume.id ? "text-electric-400" : "text-text-muted"
                          }`} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-text-primary truncate">
                              {resume.file_name}
                            </span>
                            {resume.is_active && (
                              <span className="badge badge-excellent text-[10px] flex-shrink-0">Active</span>
                            )}
                          </div>
                          <div className="text-xs text-text-muted mt-0.5">
                            {resume.skill_count} skills · {resume.total_experience_years.toFixed(1)} yrs exp · {formatRelativeDate(resume.created_at)}
                          </div>
                        </div>
                        {selectedResumeId === resume.id && (
                          <CheckCircle2 className="w-4 h-4 text-electric-400 flex-shrink-0" />
                        )}
                      </div>
                    </button>
                  ))}
                </div>

                {ownResumes.length === 0 && (
                  <div className="text-center py-4">
                    <AlertCircle className="w-8 h-8 text-text-muted mx-auto mb-2" />
                    <p className="text-sm text-text-muted">No parsed resumes available.</p>
                    <Link href="/candidate/resumes/upload" className="text-electric-400 text-xs hover:underline">
                      Upload a resume
                    </Link>
                  </div>
                )}

                <div className="flex gap-3 pt-2">
                  <button onClick={() => setPickerJobId(null)} className="btn-secondary flex-1">
                    Cancel
                  </button>
                  <button
                    onClick={() => applyMutation.mutate({ jobId: pickerJobId, resumeId: selectedResumeId })}
                    disabled={!selectedResumeId || applyMutation.isPending}
                    className="btn-primary flex-1 flex items-center justify-center gap-2"
                  >
                    {applyMutation.isPending
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : "Submit Application"
                    }
                  </button>
                </div>
              </div>
            </div>
          </Portal>
        )}

      {data?.meta && <PaginationBar meta={data?.meta} />}

      {postApplyRecs.length > 0 && (
      <div className="fixed bottom-6 right-6 w-80 card p-4 shadow-2xl border border-electric-500/20 z-50 animate-slide-up">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-display font-semibold text-text-primary text-sm">
            You might also like
          </h3>
          <button
            onClick={() => setPostApplyRecs([])}
            className="text-text-muted hover:text-text-primary"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="space-y-2">
          {postApplyRecs.map((rec: JobRecommendation) => (
            <div key={rec.job_id} className="flex items-center gap-3 p-2 rounded-lg bg-charcoal-800">
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-text-primary truncate">{rec.title}</div>
                <div className="text-xs text-text-muted">{rec.company}</div>
              </div>
              <ScoreBadge score={rec.final_score} label={rec.score_label} />
            </div>
          ))}
        </div>
        <Link href="/candidate/jobs" className="btn-primary w-full text-center text-xs mt-3">
          Browse More Jobs →
        </Link>
      </div>
    )}
    </div>
  );
}



// Add this component at the bottom of the file
function ActiveResumeIndicator({ resume }: { resume: Resume | undefined }) {
  if (!resume) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-400">
        <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
        <span>No resume uploaded. <Link href="/candidate/resumes/upload" className="underline hover:text-red-300">Upload one</Link> to apply.</span>
      </div>
    );
  }

  const isParsed = resume.parse_status === "success";

  return (
    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs ${
      isParsed
        ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
        : "bg-amber-500/10 border-amber-500/20 text-amber-400"
    }`}>
      {isParsed
        ? <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" />
        : <Loader2 className="w-3.5 h-3.5 flex-shrink-0 animate-spin" />
      }
      <span>
        Applying with: <span className="font-medium">{resume.file_name}</span>
        {!isParsed && " (processing...)"}
      </span>
      <Link
        href="/candidate/resumes"
        className="ml-auto underline hover:opacity-80 flex-shrink-0"
      >
        Change
      </Link>

      
    </div>
  );
}

// Add this component:
function FitAnalysisCard({ score }: { score: ScoreMatchResult | undefined }) {
  if (!score) return null;

  const pct = Math.round(score.final_score * 100);
  const color =
    pct >= 75 ? "emerald" :
    pct >= 50 ? "amber" : "red";

  const colorMap: Record<string, string> = {
    emerald: "bg-emerald-500/10 border-emerald-500/20 text-emerald-400",
    amber:   "bg-amber-500/10  border-amber-500/20  text-amber-400",
    red:     "bg-red-500/10    border-red-500/20    text-red-400",
  };

  const label =
    pct >= 75 ? "Strong Match" :
    pct >= 50 ? "Partial Match" : "Weak Match";

  return (
    <div className={`rounded-xl border p-3 mb-4 ${colorMap[color]}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-semibold">{label} — {pct}%</span>
        <div className="w-24 h-2 bg-black/20 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full bg-current opacity-80"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      {score.matched_skills?.length > 0 && (
        <div className="text-xs opacity-80 mb-1">
          ✓ Matched: {score.matched_skills.slice(0, 3).join(", ")}
          {score.matched_skills.length > 3 && ` +${score.matched_skills.length - 3} more`}
        </div>
      )}
      {score.missing_skills?.length > 0 && (
        <div className="text-xs opacity-80">
          ✗ Missing: {score.missing_skills.slice(0, 3).join(", ")}
          {score.missing_skills.length > 3 && ` +${score.missing_skills.length - 3} more`}
        </div>
      )}
    </div>
  );
}
