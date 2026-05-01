import { ScoreLabel } from "@/lib/types";

export const scoreColors = {
  excellent: {
    bg: "bg-emerald-500/15",
    text: "text-emerald-400",
    border: "border-emerald-500/25",
    hex: "#10B981",
    glow: "shadow-emerald-500/20",
    badgeClass: "badge-excellent",
  },
  good: {
    bg: "bg-blue-500/15",
    text: "text-blue-400",
    border: "border-blue-500/25",
    hex: "#3B82F6",
    glow: "shadow-blue-500/20",
    badgeClass: "badge-good",
  },
  fair: {
    bg: "bg-amber-500/15",
    text: "text-amber-400",
    border: "border-amber-500/25",
    hex: "#F59E0B",
    glow: "shadow-amber-500/20",
    badgeClass: "badge-fair",
  },
  weak: {
    bg: "bg-red-500/15",
    text: "text-red-400",
    border: "border-red-500/25",
    hex: "#EF4444",
    glow: "shadow-red-500/20",
    badgeClass: "badge-weak",
  },
} as const;

export function getScoreColors(label: ScoreLabel) {
  return scoreColors[label];
}

export function getScoreLabel(score: number): ScoreLabel {
  if (score >= 0.8) return "excellent";
  if (score >= 0.6) return "good";
  if (score >= 0.4) return "fair";
  return "weak";
}
