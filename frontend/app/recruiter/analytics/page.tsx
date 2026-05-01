"use client";
import { useQuery } from "@tanstack/react-query";
import { api, queryKeys } from "@/lib/api/client";
import { useAuthStore } from "@/lib/store/authStore";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, BarChart as HBarChart,
} from "recharts";
import { formatScore } from "@/lib/utils/formatters";
import { Briefcase, Users, TrendingUp, Award } from "lucide-react";
import Link from "next/link";
import { ScoreBadge } from "@/components/shared";

const PIPELINE_COLORS = [
  "#3B82F6","#8B5CF6","#06B6D4","#F59E0B","#10B981","#10B981","#EF4444","#6B7280",
];
const SCORE_COLORS = {
  excellent: "#10B981",
  good: "#3B82F6",
  fair: "#F59E0B",
  weak: "#EF4444",
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

export default function AnalyticsPage() {
  const { userId } = useAuthStore();

  // Use the full dashboard endpoint (has everything) + separate endpoints for dedicated charts
  const { data: dashData, isLoading: dashLoading } = useQuery({
    queryKey: queryKeys.analyticsBoard(userId!),
    queryFn: () => api.getAnalyticsDashboard(userId!),
    enabled: !!userId,
  });

  const { data: pipelineData } = useQuery({
    queryKey: queryKeys.analyticsPipeline(userId!),
    queryFn: () => api.getAnalyticsPipeline(userId!),
    enabled: !!userId,
  });

  const { data: scoreDistData } = useQuery({
    queryKey: queryKeys.analyticsScoreDist(userId!),
    queryFn: () => api.getAnalyticsScoreDistribution(userId!),
    enabled: !!userId,
  });

  const { data: skillsDemandData } = useQuery({
    queryKey: queryKeys.analyticsSkillsDemand(userId!),
    queryFn: () => api.getAnalyticsSkillsDemand(userId!, 15),
    enabled: !!userId,
  });

  const { data: topJobsData } = useQuery({
    queryKey: queryKeys.analyticsTopJobs(userId!),
    queryFn: () => api.getAnalyticsTopJobs(userId!, 5),
    enabled: !!userId,
  });

  const dash = dashData?.data;
  // Use dedicated pipeline endpoint data if available, fallback to dashboard
  const pipeline = pipelineData?.data ?? dash?.pipeline_funnel;
  // Use dedicated score-distribution endpoint
  const scoreDist = scoreDistData?.data ?? dash?.score_distribution;
  // Use dedicated skills-demand endpoint
  const skillsDemand = skillsDemandData?.data?.skills ?? dash?.skills_demand ?? [];
  // Use dedicated top-jobs endpoint
  const topJobs = topJobsData?.data?.jobs ?? dash?.top_jobs ?? [];

  const pipelineChartData = pipeline
    ? Object.entries(pipeline).map(([stage, count], i) => ({
        stage: stage.charAt(0).toUpperCase() + stage.slice(1),
        count,
        fill: PIPELINE_COLORS[i] ?? "#3B82F6",
      }))
    : [];

  const scoreDistChartData = scoreDist
    ? [
        { name: "Excellent", value: scoreDist.excellent, color: SCORE_COLORS.excellent },
        { name: "Good", value: scoreDist.good, color: SCORE_COLORS.good },
        { name: "Fair", value: scoreDist.fair, color: SCORE_COLORS.fair },
        { name: "Weak", value: scoreDist.weak, color: SCORE_COLORS.weak },
      ]
    : [];

  const skillsChartData = skillsDemand.slice(0, 15).map((s: any) => ({
    skill: s.skill,
    count: s.count,
  }));

  if (dashLoading) return <DashboardSkeleton />;

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-bold text-text-primary mb-1">Analytics</h1>
        <p className="text-text-secondary">Your recruitment performance at a glance</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-5 gap-4 mb-8">
        {[
          { label: "Total Jobs", value: dash?.total_jobs ?? 0, icon: Briefcase, color: "text-electric-400", bg: "bg-electric-500/10" },
          { label: "Active Jobs", value: dash?.active_jobs ?? 0, icon: Briefcase, color: "text-emerald-400", bg: "bg-emerald-500/10" },
          { label: "Applications", value: dash?.total_applications ?? 0, icon: Users, color: "text-blue-400", bg: "bg-blue-500/10" },
          { label: "Hired", value: dash?.total_hired ?? 0, icon: Award, color: "text-volt-400", bg: "bg-volt-400/10" },
          {
            label: "Avg Score",
            value: dash?.avg_score ? formatScore(dash.avg_score) : "—",
            icon: TrendingUp,
            color: "text-amber-400",
            bg: "bg-amber-500/10",
          },
        ].map((kpi) => (
          <div key={kpi.label} className="card p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-text-muted uppercase tracking-wider">{kpi.label}</span>
              <div className={`w-7 h-7 rounded-lg ${kpi.bg} flex items-center justify-center`}>
                <kpi.icon className={`w-3.5 h-3.5 ${kpi.color}`} />
              </div>
            </div>
            <div className="font-display text-2xl font-bold text-text-primary">{kpi.value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-6 mb-6">
        {/* Pipeline funnel — GET /analytics/pipeline */}
        <div className="card p-6">
          <h3 className="section-title mb-1">Application Pipeline</h3>
          <p className="text-text-muted text-xs mb-4">Source: /analytics/pipeline</p>
          {pipelineChartData.length === 0 ? (
            <div className="h-60 flex items-center justify-center text-text-muted text-sm">No data yet.</div>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={pipelineChartData} barSize={24}>
                <XAxis dataKey="stage" tick={{ fill: "#8B92A8", fontSize: 10 }} axisLine={false} tickLine={false} interval={0} angle={-30} textAnchor="end" height={60} />
                <YAxis tick={{ fill: "#8B92A8", fontSize: 11 }} axisLine={false} tickLine={false} />
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

        {/* Score distribution — GET /analytics/score-distribution */}
        <div className="card p-6">
          <h3 className="section-title mb-1">Score Distribution</h3>
          <p className="text-text-muted text-xs mb-4">Source: /analytics/score-distribution</p>
          {scoreDistChartData.every((d) => d.value === 0) ? (
            <div className="h-60 flex items-center justify-center text-text-muted text-sm">No scores yet.</div>
          ) : (
            <div className="flex items-center gap-6">
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie
                    data={scoreDistChartData}
                    cx="50%" cy="50%"
                    innerRadius={55} outerRadius={80}
                    dataKey="value" paddingAngle={3}
                  >
                    {scoreDistChartData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip content={<CustomTooltip />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-3">
                {scoreDistChartData.map((s) => (
                  <div key={s.name} className="flex items-center gap-2 text-sm">
                    <span className="w-3 h-3 rounded-full flex-shrink-0" style={{ background: s.color }} />
                    <span className="text-text-secondary">{s.name}</span>
                    <span className="text-text-primary font-semibold ml-auto pl-4">{s.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Skills demand — GET /analytics/skills-demand?top_n=15 */}
        <div className="card p-6 col-span-2">
          <h3 className="section-title mb-1">Skills in Demand</h3>
          <p className="text-text-muted text-xs mb-4">Source: /analytics/skills-demand?top_n=15</p>
          {skillsChartData.length === 0 ? (
            <div className="h-60 flex items-center justify-center text-text-muted text-sm">No skills data yet.</div>
          ) : (
            <ResponsiveContainer width="100%" height={320}>
              <HBarChart data={skillsChartData} layout="vertical" barSize={12}>
                <XAxis type="number" tick={{ fill: "#8B92A8", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis
                  type="category" dataKey="skill"
                  tick={{ fill: "#8B92A8", fontSize: 11 }}
                  axisLine={false} tickLine={false} width={120}
                />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="count" radius={[0, 4, 4, 0]} fill="#00D4FF" fillOpacity={0.8} />
              </HBarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Top jobs — GET /analytics/top-jobs?top_n=5 */}
        <div className="card p-6">
          <div className="flex items-center justify-between mb-1">
            <h3 className="section-title">Top Jobs</h3>
            <Link href="/recruiter/jobs" className="text-electric-400 text-xs hover:text-electric-300">All →</Link>
          </div>
          <p className="text-text-muted text-xs mb-4">Source: /analytics/top-jobs?top_n=5</p>
          {topJobs.length === 0 ? (
            <div className="py-8 text-center text-text-muted text-sm">No jobs yet.</div>
          ) : (
            <div className="space-y-3">
              {topJobs.map((job: any, i: number) => (
                <Link
                  key={job.job_id}
                  href={`/recruiter/jobs/${job.job_id}`}
                  className="flex items-center gap-3 p-3 rounded-lg hover:bg-charcoal-700 transition-colors group"
                >
                  <span className="font-display text-lg font-bold text-text-muted w-6">{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-text-primary truncate group-hover:text-electric-400 transition-colors">
                      {job.title}
                    </div>
                    <div className="text-xs text-text-muted">{job.applicant_count} applicants</div>
                  </div>
                  <ScoreBadge
                    score={job.avg_score}
                    label={job.avg_score >= 0.8 ? "excellent" : job.avg_score >= 0.6 ? "good" : job.avg_score >= 0.4 ? "fair" : "weak"}
                  />
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <div className="skeleton h-8 w-48 rounded-lg" />
      <div className="grid grid-cols-5 gap-4">
        {[1,2,3,4,5].map((i) => <div key={i} className="card p-5 skeleton h-24" />)}
      </div>
      <div className="grid grid-cols-2 gap-6">
        <div className="card p-6 skeleton h-72" />
        <div className="card p-6 skeleton h-72" />
      </div>
    </div>
  );
}
