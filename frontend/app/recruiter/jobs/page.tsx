"use client";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, queryKeys, getFriendlyError, getClientToken } from "@/lib/api/client";
import { useAuthStore } from "@/lib/store/authStore";
import { EmptyState, PaginationBar, TableSkeleton } from "@/components/shared";
import { formatRelativeDate } from "@/lib/utils/formatters";
import { Plus, Briefcase, MapPin, Users, ChevronRight, Search, Trash2, Zap, Loader2 } from "lucide-react";
import { toast } from "sonner";
import Link from "next/link";
import { useState, useCallback } from "react";

const STATUSES = ["draft", "active", "paused", "closed"];

export default function RecruiterJobsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { userId, userName, role, isRefreshing } = useAuthStore();

  const page = Number(searchParams.get("page") ?? 1);
  const status = searchParams.get("status") ?? "";
  const [search, setSearch] = useState(searchParams.get("search") ?? "");

  const setFilter = useCallback((key: string, value: string) => {
    const params = new URLSearchParams(searchParams.toString());
    value ? params.set(key, value) : params.delete(key);
    params.delete("page");
    router.push(`?${params}`);
  }, [searchParams, router]);


  const { data: jobsData, isLoading } = useQuery({
    queryKey: queryKeys.recruiterJobs(userId!, status || undefined),
    queryFn: () => api.getRecruiterJobs(userId!, {
      status: status || undefined,
      page,
      limit: 20,
    }),
    enabled: !!userId && role === "recruiter" && !isRefreshing && !!getClientToken(),
  });

  const enhanceMutation = useMutation({
    mutationFn: (jobId: string) => api.enhanceJob(jobId),
    onSuccess: (res, jobId) => {
      toast.success(`Job enhanced! Quality: ${Math.round((res.data.quality_score ?? 0) * 100)}%`);
      queryClient.invalidateQueries({ queryKey: queryKeys.recruiterJobs(userId!) });
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: (jobId: string) => api.deleteJob(jobId),
    onSuccess: () => {
      toast.success("Job deleted.");
      queryClient.invalidateQueries({ queryKey: queryKeys.recruiterJobs(userId!) });
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  const jobs = jobsData?.data ?? [];

  const statusColors: Record<string, string> = {
    active: "badge-excellent", draft: "badge-neutral", paused: "badge-fair", closed: "badge-weak",
  };

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="font-display text-3xl font-bold text-text-primary mb-1">Job Postings</h1>
          <p className="text-text-secondary">Manage your open positions</p>
        </div>
        <Link href="/recruiter/jobs/new" className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4" /> Post New Job
        </Link>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input className="input pl-9" placeholder="Search jobs..." value={search} onChange={(e) => { setSearch(e.target.value); setTimeout(() => setFilter("search", e.target.value), 300); }} />
        </div>
        <div className="flex gap-2">
          <button onClick={() => setFilter("status", "")} className={`badge cursor-pointer ${!status ? "badge-electric" : "badge-neutral"}`}>All</button>
          {STATUSES.map((s) => (
            <button key={s} onClick={() => setFilter("status", s)} className={`badge cursor-pointer capitalize ${status === s ? "badge-electric" : "badge-neutral"}`}>{s}</button>
          ))}
        </div>
      </div>

      {isLoading ? <TableSkeleton rows={6} /> : jobs.length === 0 ? (
        <EmptyState
          icon={<Briefcase className="w-7 h-7" />}
          title="No jobs found"
          description="Post your first job to start receiving applications."
          action={<Link href="/recruiter/jobs/new" className="btn-primary">Post a Job</Link>}
        />
      ) : (
        <div className="space-y-2">
          {jobs.map((job) => (
            <div key={job.id} className="card-hover p-4 flex items-center gap-4 group">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <Link href={`/recruiter/jobs/${job.id}`} className="font-medium text-text-primary hover:text-electric-400 transition-colors">
                    {job.title}
                  </Link>
                  <span className={`badge ${statusColors[job.status] ?? "badge-neutral"} capitalize`}>{job.status}</span>
                </div>
                <div className="flex flex-wrap gap-3 text-xs text-text-muted mt-1">
                  <span className="flex items-center gap-1"><MapPin className="w-3 h-3" />{job.location}</span>
                  <span>{job.job_type}</span>
                  <span className="flex items-center gap-1"><Users className="w-3 h-3" />{job.applicant_count ?? 0} applicants</span>
                  <span>{formatRelativeDate(job.created_at)}</span>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => enhanceMutation.mutate(job.id)}
                  disabled={enhanceMutation.isPending && enhanceMutation.variables === job.id}
                  className="btn-ghost text-xs py-1.5 px-3 flex items-center gap-1.5 text-electric-400"
                >
                  {enhanceMutation.isPending && enhanceMutation.variables === job.id
                    ? <Loader2 className="w-3 h-3 animate-spin" />
                    : <Zap className="w-3 h-3" />}
                  Enhance
                </button>
                <Link href={`/recruiter/jobs/${job.id}/pipeline`} className="btn-secondary text-xs py-1.5 px-3">
                  Pipeline
                </Link>
                <Link href={`/recruiter/jobs/${job.id}`} className="btn-ghost text-xs py-1.5 px-3">
                  Edit
                </Link>
                <button
                  onClick={() => deleteMutation.mutate(job.id)}
                  disabled={deleteMutation.isPending}
                  className="p-2 rounded-lg text-text-muted hover:text-red-400 hover:bg-red-500/10 transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {jobsData?.meta && <PaginationBar meta={jobsData.meta} />}
    </div>
  );
}
