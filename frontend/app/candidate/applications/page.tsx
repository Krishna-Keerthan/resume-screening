"use client";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, queryKeys, getFriendlyError } from "@/lib/api/client";
import { useAuthStore } from "@/lib/store/authStore";
import { StageBadge, ScoreBadge, EmptyState, PaginationBar, TableSkeleton } from "@/components/shared";
import { formatRelativeDate } from "@/lib/utils/formatters";
import { ClipboardList, ChevronRight, Trash2, Loader2, Zap } from "lucide-react";
import { toast } from "sonner";
import Link from "next/link";

const STAGES = ["applied", "reviewed", "shortlisted", "interviewing", "offered", "hired", "rejected", "withdrawn"];

export default function ApplicationsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { userId } = useAuthStore();

  const page = Number(searchParams.get("page") ?? 1);
  const stage = searchParams.get("stage") ?? "";

  const setFilter = (key: string, value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    value ? params.set(key, value) : params.delete(key);
    params.delete("page");
    router.push(`?${params}`);
  };

  const queryClient = useQueryClient();

  const withdrawMutation = useMutation({
    mutationFn: (id: string) => api.withdrawApplication(id),
    onSuccess: () => {
      toast.success("Application withdrawn.");
      queryClient.invalidateQueries({ queryKey: queryKeys.applications({ candidate_id: userId! }) });
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.applications({ candidate_id: userId!, stage, page: String(page) }),
    queryFn: () => api.listApplications({ candidate_id: userId!, stage: stage || undefined, page, limit: 20 }),
    enabled: !!userId,
  });

  const applications = data?.data ?? [];

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-bold text-text-primary mb-1">My Applications</h1>
        <p className="text-text-secondary">Track your application pipeline</p>
      </div>

      {/* Stage filter */}
      <div className="flex flex-wrap gap-2 mb-6">
        <button
          onClick={() => setFilter("stage", "")}
          className={`badge cursor-pointer ${!stage ? "badge-electric" : "badge-neutral"}`}
        >All</button>
        {STAGES.map((s) => (
          <button
            key={s}
            onClick={() => setFilter("stage", s)}
            className={`badge cursor-pointer capitalize ${stage === s ? "badge-electric" : "badge-neutral"}`}
          >{s}</button>
        ))}
      </div>

      {isLoading ? (
        <TableSkeleton rows={6} />
      ) : applications.length === 0 ? (
        <EmptyState
          icon={<ClipboardList className="w-7 h-7" />}
          title="No applications yet"
          description="Start applying to jobs to track your progress here."
          action={<Link href="/candidate/jobs" className="btn-primary">Browse Jobs</Link>}
        />
      ) : (
        <div className="space-y-2">
          {applications.map((app) => (
              <div key={app.id} className="card overflow-hidden">
                <Link
                  href={`/candidate/applications/${app.id}`}
                  className="card-hover p-4 flex items-center gap-4 group "
                >
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-text-primary group-hover:text-electric-400 transition-colors">
                      {app.job?.title ?? "Job Application"}
                    </div>
                    <div className="text-text-muted text-sm mt-0.5">
                      {app.job?.company ?? "—"} · Applied {formatRelativeDate(app.applied_at)}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {app.ats_score && (
                      <ScoreBadge score={app.ats_score.final_score} label={app.ats_score.score_label} />
                    )}
                    <StageBadge stage={app.stage} />
                    {!["hired", "rejected", "withdrawn"].includes(app.stage) && (
                      <button
                        onClick={(e) => { e.preventDefault(); withdrawMutation.mutate(app.id); }}
                        disabled={withdrawMutation.isPending}
                        className="p-1.5 rounded-lg text-text-muted hover:text-red-400 hover:bg-red-500/10 transition-colors flex-shrink-0"
                        title="Withdraw application"
                      >
                        {withdrawMutation.isPending
                          ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          : <Trash2 className="w-3.5 h-3.5" />
                        }
                      </button>
                    )}
                    <ChevronRight className="w-4 h-4 text-text-muted group-hover:text-electric-400 transition-colors" />
                  </div>
                </Link>

                {/* Improvement plan OUTSIDE the Link, below the row */}
                {app.improvement_plan && app.improvement_plan.length > 0 && (
                  <div className="border-t border-white/[0.05] px-4 pb-4 pt-3 bg-amber-500/[0.03]">
                    <p className="text-xs font-semibold text-amber-400 uppercase tracking-wider mb-2">
                      AI Improvement Coach
                    </p>
                    <div className="space-y-1.5">
                      {app.improvement_plan.slice(0, 3).map((item: any) => (
                        <div key={item.rank} className="flex items-start gap-2 text-xs">
                          <span className="w-4 h-4 rounded-full bg-amber-500/20 text-amber-400 flex items-center justify-center flex-shrink-0 font-bold text-[9px] mt-0.5">
                            {item.rank}
                          </span>
                          <div>
                            <span className="text-text-secondary">{item.action}</span>
                            <span className={`ml-2 text-[10px] ${
                              item.impact === "high"   ? "text-red-400" :
                              item.impact === "medium" ? "text-amber-400" : "text-text-muted"
                            }`}>
                              · {item.impact} impact · {item.effort}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
        </div>
      )}

      {data?.meta && <PaginationBar meta={data.meta} />}
    </div>
  );
}
