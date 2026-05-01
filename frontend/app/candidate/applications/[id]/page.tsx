"use client";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, queryKeys, getFriendlyError } from "@/lib/api/client";
import { AtsScoreCard } from "@/components/shared/AtsScoreCard";
import { StageBadge, ScoreCardSkeleton } from "@/components/shared";
import { formatRelativeDate, formatSalary } from "@/lib/utils/formatters";
import { ArrowLeft, Loader2, AlertTriangle, Zap, MapPin, Briefcase } from "lucide-react";
import { toast } from "sonner";
import Link from "next/link";

export default function ApplicationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.application(id),
    queryFn: () => api.getApplication(id),
  });

  const scoreMutation = useMutation({
    mutationFn: () => api.scoreApplication(id),
    onSuccess: () => {
      toast.success("Score refreshed!");
      queryClient.invalidateQueries({ queryKey: queryKeys.application(id) });
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  const withdrawMutation = useMutation({
    mutationFn: () => api.withdrawApplication(id),
    onSuccess: () => {
      toast.success("Application withdrawn.");
      router.push("/candidate/applications");
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  const app = data?.data;

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <Link href="/candidate/applications" className="inline-flex items-center gap-2 text-text-muted hover:text-text-primary text-sm mb-6 transition-colors">
        <ArrowLeft className="w-4 h-4" /> Back to Applications
      </Link>

      {isLoading ? (
        <ScoreCardSkeleton />
      ) : !app ? (
        <div className="card p-8 text-center">
          <AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-3" />
          <p className="text-text-secondary">Application not found.</p>
        </div>
      ) : (
        <div className="space-y-6 animate-slide-up">
          {/* Header */}
          <div className="card p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-3 mb-2">
                  <h1 className="font-display text-2xl font-bold text-text-primary">
                    {app.job?.title ?? "Application Details"}
                  </h1>
                  <StageBadge stage={app.stage} />
                </div>
                {app.job && (
                  <div className="flex flex-wrap gap-3 text-sm text-text-muted">
                    <span className="flex items-center gap-1"><Briefcase className="w-4 h-4" />{app.job.company}</span>
                    <span className="flex items-center gap-1"><MapPin className="w-4 h-4" />{app.job.location}</span>
                    {(app.job.salary_min || app.job.salary_max) && (
                      <span>{formatSalary(app.job.salary_min, app.job.salary_max, app.job.salary_currency)}</span>
                    )}
                  </div>
                )}
                <p className="text-text-muted text-xs mt-2">Applied {formatRelativeDate(app.applied_at)}</p>
              </div>

              <div className="flex gap-2">
                <button
                  onClick={() => scoreMutation.mutate()}
                  disabled={scoreMutation.isPending}
                  className="btn-secondary text-sm flex items-center gap-2"
                >
                  {scoreMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4 text-electric-400" />}
                  Refresh Score
                </button>
                {!["hired", "rejected", "withdrawn"].includes(app.stage) && (
                  <button
                    onClick={() => withdrawMutation.mutate()}
                    disabled={withdrawMutation.isPending}
                    className="btn-danger text-sm flex items-center gap-2"
                  >
                    {withdrawMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : "Withdraw"}
                  </button>
                )}
              </div>
            </div>

            {/* Recruiter notes / rejection */}
            {app.recruiter_notes && (
              <div className="mt-4 p-3 rounded-lg bg-charcoal-900 border border-white/[0.06]">
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">Recruiter Notes</p>
                <p className="text-sm text-text-secondary">{app.recruiter_notes}</p>
              </div>
            )}
            {app.rejection_reason && (
              <div className="mt-3 p-3 rounded-lg bg-red-500/5 border border-red-500/20">
                <p className="text-xs font-semibold text-red-400 uppercase tracking-wider mb-1">Rejection Reason</p>
                <p className="text-sm text-red-300/80">{app.rejection_reason}</p>
              </div>
            )}
          </div>

          {/* ATS Score */}
          {app.ats_score ? (
            <AtsScoreCard score={app.ats_score} mode="full" />
          ) : (
            <div className="card p-8 text-center">
              <Zap className="w-10 h-10 text-electric-400/40 mx-auto mb-3" />
              <p className="text-text-secondary mb-4">No score yet for this application.</p>
              <button onClick={() => scoreMutation.mutate()} disabled={scoreMutation.isPending} className="btn-primary">
                {scoreMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin inline mr-2" /> : null}
                Generate Score
              </button>
            </div>
          )}

          {/* Cover letter */}
          {app.cover_letter && (
            <div className="card p-6">
              <h3 className="font-display font-semibold text-text-primary mb-3">Cover Letter</h3>
              <p className="text-text-secondary text-sm leading-relaxed whitespace-pre-wrap">{app.cover_letter}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
