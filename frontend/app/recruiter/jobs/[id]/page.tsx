"use client";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, queryKeys, getFriendlyError } from "@/lib/api/client";
import { useAuthStore } from "@/lib/store/authStore";
import { AtsScoreCard } from "@/components/shared/AtsScoreCard";
import { SkillBadge, ScoreBadge, StageBadge } from "@/components/shared";
import { formatSalary, formatExperience, formatRelativeDate, formatScore } from "@/lib/utils/formatters";
import { EditJobTab } from "@/components/recruiter/EditJobTab"; // ← ADD THIS IMPORT
import {
  ArrowLeft, Zap, Loader2, MapPin, Briefcase, DollarSign, Users, CheckCircle2,
} from "lucide-react";
import { toast } from "sonner";
import Link from "next/link";
import { useState } from "react";
import { JobEnhancement } from "@/lib/types";

export default function RecruiterJobDetailPage() {
  const { id }          = useParams<{ id: string }>();
  const queryClient     = useQueryClient();
  const { userId }      = useAuthStore();
  const [enhancement,   setEnhancement] = useState<JobEnhancement | null>(null);
  const [activeTab,     setActiveTab]   = useState<"details" | "edit" | "candidates" | "performance">("details");

  // ── REMOVED: editSkills, useForm, editRegister, editHandleSubmit, editReset,
  //             updateMutation — all now handled inside EditJobTab ────────────

  const { data: jobData, isLoading } = useQuery({
    queryKey: queryKeys.job(id),
    queryFn:  () => api.getJob(id),
  });

  const { data: candidatesData, isLoading: candidatesLoading } = useQuery({
    queryKey: queryKeys.jobCandidates(id),
    queryFn:  () => api.getJobCandidates(id, { page: 1, limit: 20 }),
    enabled:  activeTab === "candidates",
  });

  const { data: perfData } = useQuery({
    queryKey: queryKeys.jobPerformance(id),
    queryFn:  () => api.getJobPerformance(id),
    enabled:  activeTab === "performance",
  });

  const { data: skillGapsData } = useQuery({
    queryKey: queryKeys.jobSkillGaps(id),
    queryFn:  () => api.getJobSkillGaps(id),
    enabled:  activeTab === "candidates",
  });

  // ── Enhance mutation stays here because it affects the page-level
  //    enhancement banner — separate concern from the edit form ───────────────
  const enhanceMutation = useMutation({
    mutationFn: () => api.enhanceJob(id),
    onSuccess: (res) => {
      setEnhancement(res.data);
      toast.success("Job enhanced with AI!");
      queryClient.invalidateQueries({ queryKey: queryKeys.job(id) });
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  const job = jobData?.data;

  if (isLoading) return <div className="p-8 space-y-4"><div className="card p-6 skeleton h-48" /></div>;
  if (!job)      return <div className="p-8 text-center text-text-muted">Job not found.</div>;

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <Link
        href="/recruiter/jobs"
        className="inline-flex items-center gap-2 text-text-muted hover:text-text-primary text-sm mb-6 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Back to Jobs
      </Link>

      {/* ── Job header card ──────────────────────────────────────────────── */}
      <div className="card p-6 mb-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <h1 className="font-display text-2xl font-bold text-text-primary">{job.title}</h1>
              <span className={`badge capitalize ${job.status === "active" ? "badge-excellent" : "badge-neutral"}`}>
                {job.status}
              </span>
            </div>
            <div className="flex flex-wrap gap-3 text-sm text-text-muted">
              <span className="flex items-center gap-1"><Briefcase className="w-4 h-4" />{job.company}</span>
              <span className="flex items-center gap-1"><MapPin className="w-4 h-4" />{job.location}</span>
              <span>{job.job_type}</span>
              {(job.salary_min || job.salary_max) && (
                <span className="flex items-center gap-1">
                  <DollarSign className="w-4 h-4" />
                  {formatSalary(job.salary_min, job.salary_max, job.salary_currency)}
                </span>
              )}
              {job.experience_years && <span>{formatExperience(job.experience_years)}</span>}
            </div>
            <p className="text-text-muted text-xs mt-2">Posted {formatRelativeDate(job.created_at)}</p>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => enhanceMutation.mutate()}
              disabled={enhanceMutation.isPending}
              className="btn-secondary flex items-center gap-2"
            >
              {enhanceMutation.isPending
                ? <Loader2 className="w-4 h-4 animate-spin" />
                : <Zap className="w-4 h-4 text-electric-400" />
              }
              AI Enhance
            </button>
            <Link href={`/recruiter/jobs/${id}/pipeline`} className="btn-primary flex items-center gap-2">
              <Users className="w-4 h-4" /> View Pipeline
            </Link>
          </div>
        </div>

        {/* Quality / completeness scores */}
        {(job.quality_score !== undefined || job.completeness_score !== undefined) && (
          <div className="flex gap-4 mt-4 pt-4 border-t border-white/[0.06]">
            {job.quality_score !== undefined && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-text-muted">Quality:</span>
                <span className="font-semibold text-text-primary">{formatScore(job.quality_score)}</span>
              </div>
            )}
            {job.completeness_score !== undefined && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-text-muted">Completeness:</span>
                <span className="font-semibold text-text-primary">{formatScore(job.completeness_score)}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── AI enhancement result banner ─────────────────────────────────── */}
      {enhancement && (
        <div className="card p-6 mb-6 border-electric-500/20 bg-electric-500/3">
          <div className="flex items-center gap-2 mb-4">
            <CheckCircle2 className="w-5 h-5 text-electric-400" />
            <h3 className="font-display font-semibold text-electric-400">AI Enhancement Applied</h3>
            {enhancement.llm_enhanced && (
              <span className="badge badge-electric text-[10px]">LLM Enhanced</span>
            )}
          </div>
          <div className="flex gap-4 mb-4">
            {enhancement.quality_score !== undefined && (
              <div className="card p-3 flex-1 text-center">
                <div className="font-display text-xl font-bold text-electric-400">
                  {Math.round(enhancement.quality_score * 100)}%
                </div>
                <div className="text-text-muted text-xs">Quality Score</div>
              </div>
            )}
            {enhancement.completeness_score !== undefined && (
              <div className="card p-3 flex-1 text-center">
                <div className="font-display text-xl font-bold text-volt-400">
                  {Math.round(enhancement.completeness_score * 100)}%
                </div>
                <div className="text-text-muted text-xs">Completeness</div>
              </div>
            )}
          </div>
          {enhancement?.suggestions?.length > 0 && (
            <div className="mb-4">
              <p className="text-xs text-text-muted uppercase tracking-wider mb-2">Action Items</p>
              <ul className="space-y-1.5">
                {enhancement.suggestions.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-text-secondary">
                    <span className="text-electric-400 mt-0.5 flex-shrink-0">→</span> {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {enhancement.enhanced_description && (
            <div>
              <p className="text-xs text-text-muted uppercase tracking-wider mb-2">Enhanced Description Preview</p>
              <div className="bg-charcoal-900 rounded-xl p-4 text-sm text-text-secondary leading-relaxed whitespace-pre-wrap border border-electric-500/10 max-h-48 overflow-y-auto">
                {enhancement.enhanced_description}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Tabs ─────────────────────────────────────────────────────────── */}
      <div className="flex border-b border-white/[0.06] mb-6">
        {(["details", "edit", "candidates", "performance"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2.5 text-sm font-medium transition-colors capitalize border-b-2 -mb-px ${
              activeTab === tab
                ? "text-electric-400 border-electric-400"
                : "text-text-muted border-transparent hover:text-text-primary"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* ── Tab content ──────────────────────────────────────────────────── */}

      {activeTab === "details" && (
        <div className="space-y-6 animate-fade-in">
          <div className="card p-6">
            <h3 className="font-display font-semibold text-text-primary mb-3">Description</h3>
            <p className="text-text-secondary text-sm leading-relaxed whitespace-pre-wrap">{job.description}</p>
          </div>
          {job.required_skills?.length > 0 && (
            <div className="card p-6">
              <h3 className="font-display font-semibold text-text-primary mb-3">Required Skills</h3>
              <div className="flex flex-wrap gap-2">
                {job.required_skills.map((s, i) => <SkillBadge key={i} skill={s} variant="matched" />)}
              </div>
            </div>
          )}
          {job.nice_to_have_skills?.length > 0 && (
            <div className="card p-6">
              <h3 className="font-display font-semibold text-text-primary mb-3">Nice to Have</h3>
              <div className="flex flex-wrap gap-2">
                {job.nice_to_have_skills.map((s, i) => <SkillBadge key={i} skill={s} />)}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── EDIT TAB — wired to EditJobTab component ──────────────────────
          Passes the already-fetched `job` object as a prop.
          EditJobTab owns all form state, validation, save & enhance logic.
          When it saves, it invalidates queryKeys.job(id) which causes
          this page's useQuery to refetch — details tab updates automatically. */}
      {activeTab === "edit" && (
        <div className="animate-fade-in">
          <EditJobTab job={job} />
        </div>
      )}

      {activeTab === "candidates" && (
        <div className="animate-fade-in space-y-5">
          {candidatesLoading ? (
            <div className="space-y-2">{[1,2,3].map((i) => <div key={i} className="card p-4 skeleton h-16" />)}</div>
          ) : !candidatesData?.data?.length ? (
            <div className="card p-8 text-center text-text-muted">No applicants yet.</div>
          ) : (
            <div className="space-y-2">
              {candidatesData.data.map((c) => (
                <div key={c.candidate_id} className="card-hover p-4 flex items-center gap-4">
                  <span className="font-display text-lg font-bold text-text-muted w-8 text-center">#{c.rank}</span>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-text-primary">{c.candidate_name}</div>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {c.matched_skills.slice(0, 4).map((s, i) => <SkillBadge key={i} skill={s} variant="matched" />)}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <StageBadge stage={c.stage} />
                    <ScoreBadge score={c.final_score} label={c.score_label} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {skillGapsData?.data && (
            <div className="grid grid-cols-2 gap-4">
              <div className="card p-5">
                <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-red-400 inline-block" /> Top Missing Skills
                </h4>
                <div className="space-y-2">
                  {(skillGapsData?.data?.top_missing_skills ?? []).slice(0, 8).map((item, i) => (
                    <div key={i} className="flex items-center justify-between">
                      <SkillBadge skill={item.skill} variant="missing" />
                      <span className="text-xs text-text-muted">{item.count} candidates</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="card p-5">
                <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" /> Top Matched Skills
                </h4>
                <div className="space-y-2">
                  {(skillGapsData?.data?.top_matched_skills ?? []).slice(0, 8).map((item, i) => (
                    <div key={i} className="flex items-center justify-between">
                      <SkillBadge skill={item.skill} variant="matched" />
                      <span className="text-xs text-text-muted">{item.count} candidates</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === "performance" && perfData?.data && (
        <div className="animate-fade-in grid grid-cols-3 gap-4">
          <div className="card p-5 text-center">
            <div className="font-display text-3xl font-bold text-text-primary">{perfData.data.applicant_count}</div>
            <div className="text-text-muted text-sm mt-1">Total Applicants</div>
          </div>
          <div className="card p-5 text-center">
            <div className="font-display text-3xl font-bold text-text-primary">{formatScore(perfData.data.avg_score)}</div>
            <div className="text-text-muted text-sm mt-1">Avg ATS Score</div>
          </div>
          <div className="card p-5 text-center">
            <div className="font-display text-3xl font-bold text-text-primary">{perfData.data.top_skills_matched?.length}</div>
            <div className="text-text-muted text-sm mt-1">Matched Skills</div>
          </div>
          <div className="card p-5 col-span-3">
            <h3 className="font-display font-semibold text-text-primary mb-3 text-sm">Stage Breakdown</h3>
            <div className="grid grid-cols-4 gap-2">
              {Object.entries(perfData.data.stage_breakdown).map(([stage, count]) => (
                <div key={stage} className="p-3 bg-charcoal-900 rounded-lg text-center">
                  <div className="font-bold text-text-primary">{count}</div>
                  <StageBadge stage={stage} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}