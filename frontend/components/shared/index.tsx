"use client";
import { getScoreColors, getScoreLabel } from "@/lib/utils/scoreColors";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { PaginationMeta } from "@/lib/types";
import { useRouter, useSearchParams } from "next/navigation";

// ─── Skeleton ─────────────────────────────────────────────────────────────────
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function CardSkeleton() {
  return (
    <div className="card p-5 space-y-3">
      <div className="flex items-start gap-3">
        <Skeleton className="w-10 h-10 rounded-lg flex-shrink-0" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      </div>
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-4/5" />
      <div className="flex gap-2 pt-1">
        <Skeleton className="h-5 w-16 rounded-full" />
        <Skeleton className="h-5 w-20 rounded-full" />
        <Skeleton className="h-5 w-14 rounded-full" />
      </div>
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="card p-4 flex items-center gap-4">
          <Skeleton className="w-8 h-8 rounded-full flex-shrink-0" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-4 w-1/4 ml-auto" />
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
      ))}
    </div>
  );
}

export function ScoreCardSkeleton() {
  return (
    <div className="card p-6 space-y-4">
      <div className="flex gap-4">
        <Skeleton className="w-32 h-32 rounded-full flex-shrink-0" />
        <div className="flex-1 space-y-3">
          <Skeleton className="h-5 w-24 rounded-full" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-4/5" />
        </div>
      </div>
    </div>
  );
}

// ─── Pagination ───────────────────────────────────────────────────────────────
export function PaginationBar({ meta }: { meta: PaginationMeta }) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const goTo = (page: number) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", String(page));
    router.push(`?${params}`);
  };

  if (meta.total_pages <= 1) return null;

  return (
    <div className="flex items-center justify-between mt-6">
      <span className="text-sm text-text-muted">
        Page {meta.page} of {meta.total_pages} · {meta.total} total
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => goTo(meta.page - 1)}
          disabled={!meta.has_prev}
          className="btn-ghost p-2 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        {Array.from({ length: Math.min(meta.total_pages, 7) }, (_, i) => {
          const page = i + 1;
          return (
            <button
              key={page}
              onClick={() => goTo(page)}
              className={`w-8 h-8 rounded-lg text-sm font-medium transition-all ${
                page === meta.page
                  ? "bg-electric-500/20 text-electric-400 border border-electric-500/30"
                  : "text-text-muted hover:text-text-primary hover:bg-charcoal-700"
              }`}
            >
              {page}
            </button>
          );
        })}
        <button
          onClick={() => goTo(meta.page + 1)}
          disabled={!meta.has_next}
          className="btn-ghost p-2 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────────
export function EmptyState({
  icon, title, description, action,
}: {
  icon: React.ReactNode; title: string; description?: string; action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="w-16 h-16 rounded-2xl bg-charcoal-700 border border-white/[0.07] flex items-center justify-center text-text-muted mb-4">
        {icon}
      </div>
      <h3 className="font-display font-semibold text-text-primary mb-2">{title}</h3>
      {description && <p className="text-text-muted text-sm max-w-sm mb-6">{description}</p>}
      {action}
    </div>
  );
}

// ─── Skill badge ──────────────────────────────────────────────────────────────
export function SkillBadge({ skill, variant = "default" }: { skill: string; variant?: "default" | "matched" | "missing" }) {
  const variants = {
    default: "bg-charcoal-700 text-text-secondary border-white/[0.07]",
    matched: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    missing: "bg-red-500/10 text-red-400 border-red-500/20",
  };
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${variants[variant]}`}>
      {skill}
    </span>
  );
}

// ─── Status dot ──────────────────────────────────────────────────────────────
export function StatusDot({ status }: { status: "online" | "offline" | "loading" }) {
  return (
    <span className={`w-2 h-2 rounded-full inline-block ${
      status === "online" ? "bg-emerald-400" :
      status === "offline" ? "bg-red-400" :
      "bg-amber-400 animate-pulse"
    }`} />
  );
}

// ─── Score badge ──────────────────────────────────────────────────────────────
export function ScoreBadge({ score, label }: { score: number; label: string }) {
  // Always uses scoreColors utility — never hardcoded (master prompt requirement)
  const colors = getScoreColors((label as any) || getScoreLabel(score));
  return (
    <span className={`badge ${colors.badgeClass} font-mono`}>
      {Math.round(score * 100)}%
    </span>
  );
}

// ─── Stage badge ──────────────────────────────────────────────────────────────
export function StageBadge({ stage }: { stage: string }) {
  const map: Record<string, string> = {
    applied: "badge-neutral",
    reviewed: "badge-electric",
    shortlisted: "badge-good",
    interviewing: "badge-fair",
    offered: "badge-excellent",
    hired: "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30",
    rejected: "bg-red-500/10 text-red-400 border border-red-500/20",
    withdrawn: "bg-charcoal-700 text-text-muted border border-white/[0.05]",
  };
  return (
    <span className={`badge ${map[stage] ?? "badge-neutral"} capitalize`}>
      {stage}
    </span>
  );
}
