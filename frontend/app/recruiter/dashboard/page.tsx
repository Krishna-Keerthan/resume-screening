"use client";
import { useQuery } from "@tanstack/react-query";
import { api, queryKeys, getClientToken } from "@/lib/api/client";
import { useAuthStore } from "@/lib/store/authStore";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from "recharts";
import { formatRelativeDate, formatScore } from "@/lib/utils/formatters";
import { scoreColors, getScoreColors, getScoreLabel } from "@/lib/utils/scoreColors";
import { Briefcase, Users, Award, TrendingUp, Plus, ChevronRight } from "lucide-react";
import Link from "next/link";
import { StageBadge } from "@/components/shared";

const PIPELINE_STAGE_COLORS: Record<string, string> = {
  applied: "#3B82F6", reviewed: "#8B5CF6", shortlisted: "#06B6D4",
  interviewing: "#F59E0B", offered: "#10B981", hired: "#10B981",
  rejected: "#EF4444", withdrawn: "#6B7280",
};

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-charcoal-800 border border-white/[0.1] rounded-lg p-3 text-sm shadow-xl">
      <p className="text-text-secondary mb-1">{label}</p>
      <p className="text-electric-400 font-semibold">{payload[0].value}</p>
    </div>
  );
};

export default function RecruiterDashboard() {
  const { userId, userName, role, isRefreshing } = useAuthStore();

  const { data: dashData, isLoading } = useQuery({
  queryKey: queryKeys.recruiterAnalytics(userId!),
  queryFn: () => api.getRecruiterAnalytics(userId!),
  enabled: !!userId && role === "recruiter" && !isRefreshing && !!getClientToken(),
  });

  const { data: jobsData } = useQuery({
    queryKey: queryKeys.recruiterJobs(userId!, "active"),
    queryFn: () => api.getRecruiterJobs(userId!, { status: "active", limit: 5 }),
    enabled: !!userId && role === "recruiter" && !isRefreshing && !!getClientToken(),
  });

  const dash = dashData?.data;
  const jobs = jobsData?.data ?? [];

  // Pipeline funnel chart data — from dashboard pipeline_funnel
  const pipelineChartData = dash?.pipeline_funnel
    ? Object.entries(dash.pipeline_funnel).map(([stage, count]) => ({
        stage: stage.charAt(0).toUpperCase() + stage.slice(1),
        count: count as number,
        fill: PIPELINE_STAGE_COLORS[stage] ?? "#3B82F6",
      }))
    : [];

  // Score distribution pie — uses scoreColors utility (never hardcoded)
  const scoreDistData = dash?.score_distribution
    ? [
        { name: "Excellent", value: dash.score_distribution.excellent, color: scoreColors.excellent.hex },
        { name: "Good",      value: dash.score_distribution.good,      color: scoreColors.good.hex },
        { name: "Fair",      value: dash.score_distribution.fair,      color: scoreColors.fair.hex },
        { name: "Weak",      value: dash.score_distribution.weak,      color: scoreColors.weak.hex },
      ]
    : [];

  // Top jobs — from dashboard top_jobs[]
  const topJobs: any[] = dash?.top_jobs ?? [];

  // 5 KPI cards
  const kpis = [
    { label: "Total Jobs",   value: dash?.total_jobs ?? 0,         icon: Briefcase,  color: "text-electric-400", bg: "bg-electric-500/10" },
    { label: "Active Jobs",  value: dash?.active_jobs ?? 0,        icon: Briefcase,  color: "text-emerald-400",  bg: "bg-emerald-500/10"  },
    { label: "Applications", value: dash?.total_applications ?? 0, icon: Users,      color: "text-blue-400",     bg: "bg-blue-500/10"     },
    { label: "Hired",        value: dash?.total_hired ?? 0,        icon: Award,      color: "text-volt-400",     bg: "bg-volt-400/10"     },
    { label: "Avg Score",    value: dash?.avg_score != null ? formatScore(dash.avg_score) : "—",
                                                                    icon: TrendingUp, color: "text-amber-400",    bg: "bg-amber-500/10"    },
  ];

  if (isLoading) {
    return (
      <div className="p-8 max-w-7xl mx-auto space-y-6 animate-pulse">
        <div className="skeleton h-10 w-72 rounded-lg" />
        <div className="grid grid-cols-5 gap-4">
          {[1,2,3,4,5].map(i => <div key={i} className="card p-5 skeleton h-24" />)}
        </div>
        <div className="grid grid-cols-2 gap-6">
          <div className="card skeleton h-60" />
          <div className="card skeleton h-60" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="font-display text-3xl font-bold text-text-primary">
            Welcome, <span className="text-volt-400">{userName?.split(" ")[0]}</span>
          </h1>
          <p className="text-text-secondary mt-1">Here&apos;s your recruitment overview.</p>
        </div>
        <Link href="/recruiter/jobs/new" className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4" /> Post Job
        </Link>
      </div>

      {/* 5 KPI Cards */}
      <div className="grid grid-cols-5 gap-4 mb-8">
        {kpis.map((k) => (
          <div key={k.label} className="card p-5 flex items-center gap-3">
            <div className={`w-10 h-10 rounded-xl ${k.bg} flex items-center justify-center flex-shrink-0`}>
              <k.icon className={`w-5 h-5 ${k.color}`} />
            </div>
            <div>
              <div className="font-display text-2xl font-bold text-text-primary">{k.value}</div>
              <div className="text-text-muted text-xs">{k.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Recharts row: Pipeline funnel + Score distribution */}
      <div className="grid grid-cols-2 gap-6 mb-6">
        {/* Pipeline Funnel — from /analytics/dashboard pipeline_funnel */}
        <div className="card p-6">
          <h3 className="section-title mb-4">Pipeline Funnel</h3>
          {pipelineChartData.length === 0 ? (
            <div className="h-48 flex items-center justify-center text-text-muted text-sm">No pipeline data yet.</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={pipelineChartData} barSize={22}>
                <XAxis dataKey="stage" tick={{ fill: "#8B92A8", fontSize: 10 }} axisLine={false} tickLine={false} interval={0} angle={-30} textAnchor="end" height={50} />
                <YAxis tick={{ fill: "#8B92A8", fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {pipelineChartData.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} fillOpacity={0.9} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Score Distribution Pie — from /analytics/dashboard score_distribution — uses scoreColors */}
        <div className="card p-6">
          <h3 className="section-title mb-4">Score Distribution</h3>
          {scoreDistData.every(d => d.value === 0) ? (
            <div className="h-48 flex items-center justify-center text-text-muted text-sm">No scores yet.</div>
          ) : (
            <div className="flex items-center gap-6">
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie data={scoreDistData} cx="50%" cy="50%" innerRadius={50} outerRadius={76} dataKey="value" paddingAngle={3}>
                    {scoreDistData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip content={<CustomTooltip />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-2.5">
                {scoreDistData.map((s) => (
                  <div key={s.name} className="flex items-center gap-2 text-sm">
                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: s.color }} />
                    <span className="text-text-secondary">{s.name}</span>
                    <span className="font-semibold text-text-primary ml-auto pl-4">{s.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Bottom row: Active jobs + Top jobs table */}
      <div className="grid grid-cols-5 gap-6">
        {/* Active jobs — quick links */}
        <div className="col-span-3">
          <div className="flex items-center justify-between mb-4">
            <h2 className="section-title">Active Jobs</h2>
            <Link href="/recruiter/jobs" className="text-electric-400 text-sm hover:text-electric-300 transition-colors">View all →</Link>
          </div>
          {jobs.length === 0 ? (
            <div className="card p-8 text-center">
              <Briefcase className="w-10 h-10 text-text-muted mx-auto mb-3" />
              <p className="text-text-secondary text-sm mb-4">No active jobs yet.</p>
              <Link href="/recruiter/jobs/new" className="btn-primary inline-flex items-center gap-2">
                <Plus className="w-4 h-4" /> Post your first job
              </Link>
            </div>
          ) : (
            <div className="space-y-2">
              {jobs.map((job) => (
                <Link key={job.id} href={`/recruiter/jobs/${job.id}`} className="card-hover p-4 flex items-center gap-4 group">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-text-primary group-hover:text-electric-400 transition-colors truncate">{job.title}</div>
                    <div className="text-text-muted text-xs mt-0.5">{job.location} · {job.job_type} · {formatRelativeDate(job.created_at)}</div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="text-xs text-text-muted">{job.applicant_count ?? 0} applicants</span>
                    <ChevronRight className="w-4 h-4 text-text-muted group-hover:text-electric-400 transition-colors" />
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Top jobs table — from /analytics/dashboard top_jobs[] */}
        <div className="col-span-2 space-y-4">
          <div className="card p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-display font-semibold text-text-primary">Top Jobs by Score</h3>
              <Link href="/recruiter/analytics" className="text-electric-400 text-xs hover:text-electric-300">Analytics →</Link>
            </div>
            {topJobs.length === 0 ? (
              <p className="text-text-muted text-sm py-3">No data yet.</p>
            ) : (
              <div className="divide-y divide-white/[0.04]">
                {topJobs.slice(0, 5).map((job: any, i: number) => {
                  const label = getScoreLabel(job.avg_score ?? 0);
                  const colors = getScoreColors(label);
                  return (
                    <Link key={job.job_id} href={`/recruiter/jobs/${job.job_id}`}
                      className="flex items-center gap-3 py-2.5 hover:bg-charcoal-700/50 rounded-lg px-2 -mx-2 transition-colors group">
                      <span className="font-display text-base font-bold text-text-muted w-5">{i + 1}</span>
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium text-text-primary truncate group-hover:text-electric-400 transition-colors">{job.title}</div>
                        <div className="text-[10px] text-text-muted">{job.applicant_count} applicants</div>
                      </div>
                      <span className={`badge ${colors.badgeClass} text-[10px]`}>
                        {Math.round((job.avg_score ?? 0) * 100)}%
                      </span>
                    </Link>
                  );
                })}
              </div>
            )}
          </div>

          {/* Pipeline summary mini */}
          <div className="card p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-display font-semibold text-text-primary">Pipeline</h3>
              <Link href="/recruiter/analytics" className="text-electric-400 text-xs hover:text-electric-300">Details →</Link>
            </div>
            <div className="space-y-1.5">
              {dash?.pipeline_funnel
                ? Object.entries(dash.pipeline_funnel).slice(0, 6).map(([stage, count]) => {
                    const pct = dash.total_applications > 0 ? (count as number) / dash.total_applications : 0;
                    return (
                      <div key={stage} className="flex items-center gap-2">
                        <StageBadge stage={stage} />
                        <div className="flex-1 h-1.5 bg-charcoal-900 rounded-full overflow-hidden">
                          <div className="h-full bg-electric-500/60 rounded-full transition-all" style={{ width: `${pct * 100}%` }} />
                        </div>
                        <span className="text-xs font-semibold text-text-primary w-5 text-right">{count as number}</span>
                      </div>
                    );
                  })
                : <p className="text-text-muted text-sm py-1">No data yet.</p>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
