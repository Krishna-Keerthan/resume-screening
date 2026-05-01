"use client";
import { useAuthStore } from "@/lib/store/authStore";
import { useQuery } from "@tanstack/react-query";
import { api, queryKeys, getClientToken } from "@/lib/api/client";
import { CardSkeleton, ScoreBadge, SkillBadge, EmptyState, StageBadge } from "@/components/shared";
import { formatRelativeDate, formatSalary } from "@/lib/utils/formatters";
import { Briefcase, FileText, ClipboardList, TrendingUp, ChevronRight, Plus } from "lucide-react";
import Link from "next/link";
import { JobRecommendation, Resume } from "@/lib/types";

export default function CandidateDashboard() {
  const { userId, userName, isRefreshing  } = useAuthStore();

  const { data: candidateData } = useQuery({
  queryKey: queryKeys.candidate(userId!),
  queryFn: () => api.getCandidate(userId!),
  enabled: !!userId && !isRefreshing && !!getClientToken(), // ← add guards
});

  const { data: resumesData } = useQuery({
    queryKey: queryKeys.candidateResumes(userId!),
    queryFn: () => api.getCandidateResumes(userId!),
    enabled: !!userId && !isRefreshing && !!getClientToken(),
  });

  const { data: applicationsData } = useQuery({
    queryKey: queryKeys.applications({ candidate_id: userId! }),
    queryFn: () => api.listApplications({ candidate_id: userId!, limit: 5 }),
    enabled: !!userId && !isRefreshing && !!getClientToken(),
  });

  const { data: winRateData } = useQuery({
    queryKey: ["win-rate-insights", userId],
    queryFn:  () => api.getCandidateWinRateInsights(userId!),
    enabled:  !!userId && !isRefreshing && !!getClientToken(),
  });

  const activeResume = resumesData?.data?.find((r) => r.is_active && r.parse_status === "success");

  // Master prompt: use POST /scores/job-recommendations with resume_id
  const { data: recommendationsData, isLoading: recLoading } = useQuery({
    queryKey: ["job-recommendations", activeResume?.id],
    queryFn: () => api.jobRecommendations(activeResume!.id, { top_n: 6 }),
    enabled: !!activeResume?.id,
  });

  const { data: skillGapsData } = useQuery({
    queryKey: ["candidate-skill-gaps", userId],
    queryFn: () => api.getCandidateSkillGaps(userId!),
    enabled: !!userId && !isRefreshing && !!getClientToken(),
  });

  const applications = applicationsData?.data ?? [];
  const recommendations = recommendationsData?.data?.recommendations ?? [];

  const stats = [
    { label: "Resumes", value: resumesData?.data?.length ?? 0, icon: FileText, href: "/candidate/resumes" },
    { label: "Applications", value: applications.length, icon: ClipboardList, href: "/candidate/applications" },
    { label: "Matches", value: recommendationsData?.data?.total ?? 0, icon: TrendingUp, href: "/candidate/jobs" },
  ];

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-display text-3xl font-bold text-text-primary">
          Welcome back, <span className="text-electric-400">{userName?.split(" ")[0]}</span> 👋
        </h1>
        <p className="text-text-secondary mt-1">Here&apos;s what&apos;s happening with your job search.</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        {stats.map((s) => (
          <Link key={s.label} href={s.href} className="card-hover p-5 flex items-center gap-4 group">
            <div className="w-10 h-10 rounded-xl bg-electric-500/10 flex items-center justify-center">
              <s.icon className="w-5 h-5 text-electric-400" />
            </div>
            <div>
              <div className="font-display text-2xl font-bold text-text-primary">{s.value}</div>
              <div className="text-text-muted text-sm">{s.label}</div>
            </div>
            <ChevronRight className="w-4 h-4 text-text-muted ml-auto group-hover:text-electric-400 transition-colors" />
          </Link>
        ))}
      </div>

      {/* <div className="grid grid-cols-2 gap-4 mb-6">
        <ReadinessScore resumes={resumesData?.data ?? []} applications={applications} />
        <SkillGapHeatmap gaps={skillGapsData?.data?.skill_gaps ?? []} />
      </div>

      {(winRateData?.data?.top_performing_skills?.length ?? 0) > 0 && (
        <div className="mb-6">
          <WinRateInsights insights={winRateData!.data!.top_performing_skills} />
        </div>
      )} */}


      <div className="grid grid-cols-5 gap-6">
        {/* Job recommendations */}
        <div className="col-span-3">
          <div className="flex items-center justify-between mb-4">
            <h2 className="section-title">Recommended Jobs</h2>
            <Link href="/candidate/jobs" className="text-electric-400 text-sm hover:text-electric-300 transition-colors">
              View all →
            </Link>
          </div>

          {!activeResume ? (
            <div className="card p-6 text-center">
              <FileText className="w-10 h-10 text-text-muted mx-auto mb-3" />
              <p className="text-text-secondary text-sm mb-4">Upload a resume to get personalized job recommendations.</p>
              <Link href="/candidate/resumes/upload" className="btn-primary inline-flex items-center gap-2">
                <Plus className="w-4 h-4" /> Upload Resume
              </Link>
            </div>
          ) : recLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => <CardSkeleton key={i} />)}
            </div>
          ) : recommendations.length === 0 ? (
            <EmptyState icon={<Briefcase className="w-7 h-7" />} title="No recommendations yet" description="Your recommendations will appear here once jobs are available." />
          ) : (
            <div className="space-y-3">
              {recommendations.map((rec) => (
                <RecommendationCard key={rec.job_id} rec={rec} />
              ))}
            </div>
          )}
        </div>

        {/* Recent applications */}
        <div className="col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h2 className="section-title">Recent Applications</h2>
            <Link href="/candidate/applications" className="text-electric-400 text-sm hover:text-electric-300 transition-colors">
              View all →
            </Link>
          </div>

          {applications.length === 0 ? (
            <div className="card p-5 text-center">
              <p className="text-text-muted text-sm">No applications yet. Start applying!</p>
            </div>
          ) : (
            <div className="space-y-2">
              {applications.slice(0, 5).map((app) => (
                <Link key={app.id} href={`/candidate/applications/${app.id}`} className="card-hover p-4 flex items-center gap-3 group ">
                  <div className="w-8 h-8 rounded-lg bg-charcoal-700 flex items-center justify-center">
                    <Briefcase className="w-4 h-4 text-text-muted" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-text-primary truncate">{app.job?.title ?? "Job Application"}</div>
                    <div className="text-xs text-text-muted">{formatRelativeDate(app.applied_at)}</div>
                  </div>
                  <StageBadge stage={app.stage} />
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RecommendationCard({ rec }: { rec: JobRecommendation }) {
  return (
    <Link href={`/candidate/jobs/${rec.job_id}`} className="card-hover p-4 flex items-start gap-3 group">
      <div className="w-10 h-10 rounded-xl bg-charcoal-700 flex items-center justify-center flex-shrink-0">
        <Briefcase className="w-5 h-5 text-text-muted" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="font-medium text-text-primary text-sm group-hover:text-electric-400 transition-colors">{rec.title}</div>
            <div className="text-text-muted text-xs mt-0.5">{rec.company} · {rec.location}</div>
          </div>
          <ScoreBadge score={rec.final_score} label={rec.score_label} />
        </div>
        <div className="flex flex-wrap gap-1 mt-2">
          {rec.matched_skills.slice(0, 4).map((s, i) => (
            <SkillBadge key={i} skill={s} variant="matched" />
          ))}
        </div>
      </div>
    </Link>
  );
}


// Add this component at the bottom of the file
function ReadinessScore({ resumes, applications }: {
  resumes: Resume[];
  applications: any[];
}) {
  const activeResume = resumes.find((r) => r.is_active);
  const parsedResume = resumes.find((r) => r.parse_status === "success");

  // Compute score components
  const components = [
    {
      label: "Active Resume",
      score: activeResume ? 25 : 0,
      max: 25,
      tip: activeResume ? "Active resume set" : "Set a resume as active",
    },
    {
      label: "Resume Parsed",
      score: parsedResume ? 20 : 0,
      max: 20,
      tip: parsedResume ? "Resume successfully parsed" : "Upload a parseable resume",
    },
    {
      label: "Skills",
      score: Math.min(20, Math.round(((parsedResume?.skill_count ?? 0) / 10) * 20)),
      max: 20,
      tip: `${parsedResume?.skill_count ?? 0} skills detected (10+ for full score)`,
    },
    {
      label: "Experience",
      score: Math.min(15, Math.round(((parsedResume?.total_experience_years ?? 0) / 2) * 15)),
      max: 15,
      tip: `${parsedResume?.total_experience_years?.toFixed(1) ?? 0} years (2+ for full score)`,
    },
    {
      label: "Applications",
      score: Math.min(20, applications.length * 4),
      max: 20,
      tip: `${applications.length} applications submitted`,
    },
  ];

  const total = components.reduce((sum, c) => sum + c.score, 0);
  const label =
    total >= 80 ? { text: "Job Ready", color: "text-emerald-400" } :
    total >= 60 ? { text: "Good Progress", color: "text-electric-400" } :
    total >= 40 ? { text: "Getting Started", color: "text-amber-400" } :
                  { text: "Needs Attention", color: "text-red-400" };

  const circumference = 2 * Math.PI * 40;
  const strokeDash = (total / 100) * circumference;

  return (
    <div className="card p-6">
      <h3 className="font-display font-semibold text-text-primary mb-4">
        Job Readiness Score
      </h3>
      <div className="flex items-center gap-6">
        {/* Circular progress */}
        <div className="relative flex-shrink-0">
          <svg width="100" height="100" className="-rotate-90">
            <circle cx="50" cy="50" r="40" fill="none"
              stroke="currentColor" strokeWidth="8"
              className="text-charcoal-700" />
            <circle cx="50" cy="50" r="40" fill="none"
              stroke="currentColor" strokeWidth="8"
              strokeDasharray={`${strokeDash} ${circumference}`}
              strokeLinecap="round"
              className={
                total >= 80 ? "text-emerald-400" :
                total >= 60 ? "text-electric-400" :
                total >= 40 ? "text-amber-400" : "text-red-400"
              }
              style={{ transition: "stroke-dasharray 0.8s ease" }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className={`font-display text-xl font-bold ${label.color}`}>{total}</span>
            <span className="text-text-muted text-[10px]">/ 100</span>
          </div>
        </div>
        

        {/* Breakdown */}
        <div className="flex-1 space-y-2">
          <p className={`font-semibold text-sm ${label.color} mb-3`}>{label.text}</p>
          {components.map((c) => (
            <div key={c.label} className="flex items-center gap-2">
              <div className="w-24 text-xs text-text-muted flex-shrink-0">{c.label}</div>
              <div className="flex-1 h-1.5 bg-charcoal-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    c.score === c.max ? "bg-emerald-400" :
                    c.score > 0 ? "bg-electric-500" : "bg-charcoal-600"
                  }`}
                  style={{ width: `${(c.score / c.max) * 100}%` }}
                />
              </div>
              <span className="text-xs text-text-muted w-10 text-right">
                {c.score}/{c.max}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SkillGapHeatmap({ gaps }: {
  gaps: { skill: string; count: number; pct: number }[]
}) {
  if (!gaps || gaps.length === 0) return null;
  const max = gaps[0]?.count ?? 1;

  return (
    <div className="card p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-display font-semibold text-text-primary">
          Skills to Learn
        </h3>
        <span className="text-xs text-text-muted">Most missed across applications</span>
      </div>
      <div className="space-y-2.5">
        {gaps.slice(0, 8).map((g) => (
          <div key={g.skill} className="flex items-center gap-3">
            <span className="text-sm text-text-secondary w-28 truncate capitalize flex-shrink-0">
              {g.skill}
            </span>
            <div className="flex-1 h-2 bg-charcoal-800 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-amber-500 to-red-500"
                style={{ width: `${(g.count / max) * 100}%` }}
              />
            </div>
            <span className="text-xs text-text-muted w-16 text-right flex-shrink-0">
              {g.count} app{g.count !== 1 ? "s" : ""}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}


function WinRateInsights({ insights }: {
  insights: { skill: string; win_rate: number; wins: number; total: number }[]
}) {
  if (!insights || insights.length === 0) return null;

  return (
    <div className="card p-6">
      <h3 className="font-display font-semibold text-text-primary mb-4">
        Your Winning Skills
      </h3>
      <p className="text-xs text-text-muted mb-3">
        Skills that correlate with interview callbacks
      </p>
      <div className="space-y-2.5">
        {insights.map((item) => (
          <div key={item.skill} className="flex items-center gap-3">
            <span className="text-sm text-text-secondary w-28 truncate capitalize flex-shrink-0">
              {item.skill}
            </span>
            <div className="flex-1 h-2 bg-charcoal-800 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-electric-500 to-emerald-400"
                style={{ width: `${item.win_rate * 100}%` }}
              />
            </div>
            <span className="text-xs text-emerald-400 w-12 text-right flex-shrink-0">
              {Math.round(item.win_rate * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
