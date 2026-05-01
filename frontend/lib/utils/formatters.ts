export function formatScore(score: number): string {
  return `${Math.round(score * 100)}%`;
}

export function formatScoreNumber(score: number): number {
  return Math.round(score * 100);
}

export function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatRelativeDate(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

export function formatSalary(min?: number, max?: number, currency = "USD"): string {
  if (!min && !max) return "Salary not specified";
  const fmt = (n: number) =>
    n >= 1000 ? `${(n / 1000).toFixed(0)}k` : String(n);
  const sym = currency === "USD" ? "$" : currency;
  if (min && max) return `${sym}${fmt(min)} – ${sym}${fmt(max)}`;
  if (min) return `From ${sym}${fmt(min)}`;
  return `Up to ${sym}${fmt(max!)}`;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatExperience(years: number): string {
  if (years === 0) return "No experience required";
  if (years === 1) return "1 year";
  return `${years}+ years`;
}

export const STAGE_LABELS: Record<string, string> = {
  applied: "Applied",
  reviewed: "Reviewed",
  shortlisted: "Shortlisted",
  interviewing: "Interviewing",
  offered: "Offered",
  hired: "Hired",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

export const STAGE_COLORS: Record<string, string> = {
  applied: "badge-neutral",
  reviewed: "badge-electric",
  shortlisted: "badge-good",
  interviewing: "badge-fair",
  offered: "badge-excellent",
  hired: "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30",
  rejected: "bg-red-500/10 text-red-400 border border-red-500/20",
  withdrawn: "bg-charcoal-600 text-text-muted border border-white/5",
};

export function cn(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(" ");
}
