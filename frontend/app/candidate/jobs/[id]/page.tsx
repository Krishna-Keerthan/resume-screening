"use client";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/lib/store/authStore";
import { api, queryKeys, getFriendlyError } from "@/lib/api/client";
import { AtsScoreCard } from "@/components/shared/AtsScoreCard";
import { SkillBadge, ScoreBadge, ScoreCardSkeleton } from "@/components/shared";
import { formatSalary, formatExperience, formatRelativeDate } from "@/lib/utils/formatters";
import {
  ArrowLeft, MapPin, Briefcase, DollarSign, Clock, Loader2,
  CheckCircle2, AlertTriangle, Send, ChevronDown,
} from "lucide-react";
import { toast } from "sonner";
import Link from "next/link";
import { useState } from "react";
import { ScoreMatchResult } from "@/lib/types";

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { userId } = useAuthStore();

  const [coverLetter, setCoverLetter] = useState("");
  const [selectedResumeId, setSelectedResumeId] = useState<string>("");
  const [preview, setPreview] = useState<ScoreMatchResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const { data: jobData, isLoading } = useQuery({
    queryKey: queryKeys.job(id),
    queryFn: () => api.getJob(id),
  });

  const { data: resumesData } = useQuery({
    queryKey: queryKeys.candidateResumes(userId!),
    queryFn: () => api.getCandidateResumes(userId!),
    enabled: !!userId,
  });

  const activeResumes = resumesData?.data?.filter((r) => r.is_active && r.parse_status === "success") ?? [];
  const activeResume = activeResumes.find((r) => r.id === selectedResumeId) ?? activeResumes[0];

  const loadPreview = async () => {
    if (!activeResume) { toast.error("Upload a resume first to preview your match."); return; }
    setPreviewLoading(true);
    try {
      const res = await api.getScorePreview(activeResume.id, id);
      setPreview(res.data);
    } catch (err) {
      toast.error(getFriendlyError(err));
    } finally {
      setPreviewLoading(false);
    }
  };

  const applyMutation = useMutation({
    mutationFn: () =>
      api.createApplication({
        candidate_id: userId!,
        job_id: id,
        resume_id: activeResume!.id,
        cover_letter: coverLetter || undefined,
      }),
    onSuccess: (res) => {
      toast.success("Application submitted!");
      queryClient.invalidateQueries({ queryKey: queryKeys.applications({ candidate_id: userId! }) });
      router.push(`/candidate/applications/${res.data.id}`);
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  const job = jobData?.data;

  if (isLoading) return (
    <div className="p-8 max-w-4xl mx-auto">
      <div className="skeleton h-8 w-48 mb-6 rounded-lg" />
      <ScoreCardSkeleton />
    </div>
  );

  if (!job) return (
    <div className="p-8 text-center">
      <AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-3" />
      <p className="text-text-secondary">Job not found.</p>
    </div>
  );

  const scoreValue = preview?.final_score ?? 0;
  const isGreatMatch = scoreValue >= 0.8;
  const isWeakMatch = scoreValue > 0 && scoreValue < 0.5;

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <Link href="/candidate/jobs" className="inline-flex items-center gap-2 text-text-muted hover:text-text-primary text-sm mb-6 transition-colors">
        <ArrowLeft className="w-4 h-4" /> Back to Jobs
      </Link>

      {/* Great match banner */}
      {isGreatMatch && (
        <div className="card p-4 mb-4 flex items-center gap-3 border-emerald-500/30 bg-emerald-500/5 animate-slide-up">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0" />
          <span className="text-emerald-300 font-medium">Great Match! You&apos;re highly qualified for this role.</span>
          <ScoreBadge score={scoreValue} label="excellent" />
        </div>
      )}

      {/* Improve before applying */}
      {isWeakMatch && (
        <div className="card p-4 mb-4 border-amber-500/30 bg-amber-500/5 animate-slide-up">
          <div className="flex items-center gap-3 mb-2">
            <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0" />
            <span className="text-amber-300 font-medium">Consider Improving Before Applying</span>
            <ScoreBadge score={scoreValue} label={preview!.score_label} />
          </div>
          {preview?.missing_skills && preview.missing_skills.length > 0 && (
            <div>
              <p className="text-text-muted text-xs mb-2">Missing key skills:</p>
              <div className="flex flex-wrap gap-1">
                {preview.missing_skills.slice(0, 8).map((s, i) => (
                  <SkillBadge key={i} skill={s} variant="missing" />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-3 gap-6">
        {/* Left: Job details */}
        <div className="col-span-2 space-y-5">
          {/* Header */}
          <div className="card p-6">
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <h1 className="font-display text-2xl font-bold text-text-primary mb-1">{job.title}</h1>
                <div className="flex flex-wrap gap-3 text-sm text-text-muted">
                  <span className="flex items-center gap-1"><Briefcase className="w-4 h-4" />{job.company}</span>
                  <span className="flex items-center gap-1"><MapPin className="w-4 h-4" />{job.location}</span>
                  <span className="flex items-center gap-1"><Clock className="w-4 h-4" />{job.job_type}</span>
                  {(job.salary_min || job.salary_max) && (
                    <span className="flex items-center gap-1">
                      <DollarSign className="w-4 h-4" />
                      {formatSalary(job.salary_min, job.salary_max, job.salary_currency)}
                    </span>
                  )}
                  {job.experience_years && (
                    <span>{formatExperience(job.experience_years)}</span>
                  )}
                </div>
                <p className="text-text-muted text-xs mt-2">Posted {formatRelativeDate(job.created_at)}</p>
              </div>
              <span className={`badge capitalize flex-shrink-0 ${job.status === "active" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : "badge-neutral"}`}>
                {job.status}
              </span>
            </div>

            <p className="text-text-secondary text-sm leading-relaxed whitespace-pre-wrap">{job.description}</p>
          </div>

          {/* Required Skills */}
          {job.required_skills.length > 0 && (
            <div className="card p-5">
              <h3 className="font-display font-semibold text-text-primary mb-3 text-sm uppercase tracking-wider">Required Skills</h3>
              <div className="flex flex-wrap gap-2">
                {job.required_skills.map((s, i) => (
                  <SkillBadge
                    key={i}
                    skill={s}
                    variant={preview?.matched_skills?.includes(s) ? "matched" : preview ? "missing" : "default"}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Nice to have */}
          {job.nice_to_have_skills.length > 0 && (
            <div className="card p-5">
              <h3 className="font-display font-semibold text-text-primary mb-3 text-sm uppercase tracking-wider">Nice to Have</h3>
              <div className="flex flex-wrap gap-2">
                {job.nice_to_have_skills.map((s, i) => <SkillBadge key={i} skill={s} />)}
              </div>
            </div>
          )}

          {/* Responsibilities */}
          {job.responsibilities.length > 0 && (
            <div className="card p-5">
              <h3 className="font-display font-semibold text-text-primary mb-3 text-sm uppercase tracking-wider">Responsibilities</h3>
              <ul className="space-y-2">
                {job.responsibilities.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-text-secondary">
                    <span className="text-electric-400 mt-1 flex-shrink-0">→</span>
                    {r}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Right: Apply + Score panel */}
        <div className="space-y-4">
          {/* Apply card */}
          <div className="card p-5 space-y-4">
            <h3 className="font-display font-semibold text-text-primary">Apply Now</h3>

            {activeResumes.length === 0 ? (
              <div className="text-center py-4">
                <p className="text-text-muted text-sm mb-3">No resume uploaded yet.</p>
                <Link href="/candidate/resumes/upload" className="btn-primary w-full text-center block">
                  Upload Resume
                </Link>
              </div>
            ) : (
              <>
                {/* Resume selector */}
                <div>
                  <label className="label">Select Resume</label>
                  <div className="relative">
                    <select
                      className="input appearance-none pr-8"
                      value={selectedResumeId || activeResume?.id}
                      onChange={(e) => setSelectedResumeId(e.target.value)}
                    >
                      {activeResumes.map((r) => (
                        <option key={r.id} value={r.id}>{r.file_name}</option>
                      ))}
                    </select>
                    <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted pointer-events-none" />
                  </div>
                </div>

                {/* Cover letter */}
                <div>
                  <label className="label">Cover Letter <span className="text-text-muted">(optional)</span></label>
                  <textarea
                    className="input min-h-[100px] resize-y"
                    placeholder="Tell them why you're a great fit..."
                    value={coverLetter}
                    onChange={(e) => setCoverLetter(e.target.value)}
                    maxLength={5000}
                  />
                  <p className="text-text-muted text-xs mt-1 text-right">{coverLetter.length}/5000</p>
                </div>

                {/* Preview match button */}
                <button
                  onClick={loadPreview}
                  disabled={previewLoading || !activeResume}
                  className="btn-secondary w-full flex items-center justify-center gap-2"
                >
                  {previewLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  {preview ? "Refresh Score Preview" : "Preview My Match Score"}
                </button>

                {/* Apply button */}
                <button
                  onClick={() => applyMutation.mutate()}
                  disabled={applyMutation.isPending || !activeResume || job.status !== "active"}
                  className="btn-primary w-full flex items-center justify-center gap-2"
                >
                  {applyMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                  {job.status !== "active" ? "Job Closed" : "Submit Application"}
                </button>

                {job.status !== "active" && (
                  <p className="text-red-400 text-xs text-center">This job is no longer accepting applications.</p>
                )}
              </>
            )}
          </div>

          {/* Score preview card */}
          {previewLoading && (
            <ScoreCardSkeleton />
          )}
          {preview && !previewLoading && (
            <AtsScoreCard score={preview} mode="preview" />
          )}
        </div>
      </div>
    </div>
  );
}
