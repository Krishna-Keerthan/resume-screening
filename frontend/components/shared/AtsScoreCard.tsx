"use client";
import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AtsScore, ScoreLabel } from "@/lib/types";
import { getScoreColors } from "@/lib/utils/scoreColors";
import { formatScoreNumber } from "@/lib/utils/formatters";
import {
  CheckCircle2, XCircle, AlertCircle, ChevronDown, ChevronUp, Zap, Info,
} from "lucide-react";

interface AtsScoreCardProps {
  score: AtsScore;
  mode?: "preview" | "full";
  className?: string;
}

export function AtsScoreCard({ score, mode = "full", className = "" }: AtsScoreCardProps) {
  const colors = getScoreColors(score.score_label) ?? { hex: "#ccc", bg: "bg-gray-700", text: "text-white", border: "border-gray-600" };
  const [openPriority, setOpenPriority] = useState<string | null>("high");
  const [animatedScore, setAnimatedScore] = useState(0);
  const animRef = useRef<number | null>(null);

  // Count-up animation
  useEffect(() => {
    const target = formatScoreNumber(score.final_score);
    const duration = 1200;
    const start = Date.now();
    const tick = () => {
      const elapsed = Date.now() - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setAnimatedScore(Math.round(eased * target));
      if (progress < 1) animRef.current = requestAnimationFrame(tick);
    };
    animRef.current = requestAnimationFrame(tick);
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current); };
  }, [score.final_score]);

  const grouped = groupTips(score.improvement_tips ?? []);
  const circumference = 2 * Math.PI * 54;
  const offset = circumference - (score.final_score * circumference);

  return (
    <div className={`card overflow-hidden ${className}`}>
      {/* Header */}
      <div className="p-6 border-b border-white/[0.06]">
        <div className="flex items-start justify-between gap-4">
          {/* Score gauge */}
          <div className="relative w-32 h-32 flex-shrink-0">
            <svg className="w-32 h-32 -rotate-90" viewBox="0 0 120 120">
              <circle cx="60" cy="60" r="54" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8" />
              <motion.circle
                cx="60" cy="60" r="54" fill="none"
                stroke={colors?.hex ?? "#ccc"} strokeWidth="8"
                strokeLinecap="round"
                strokeDasharray={circumference}
                initial={{ strokeDashoffset: circumference }}
                animate={{ strokeDashoffset: offset }}
                transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1] }}
                style={{ filter: `drop-shadow(0 0 8px ${colors?.hex ?? "#ccc"}80)` }}
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="font-display text-3xl font-bold text-text-primary leading-none">
                {animatedScore}
              </span>
              <span className="text-text-muted text-xs mt-0.5">/ 100</span>
            </div>
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <span className={`badge ${colors.bg} ${colors.text} border ${colors.border} uppercase text-[11px] tracking-wider font-bold`}>
                {score.score_label}
              </span>
              {mode === "preview" && (
                <span className="badge bg-charcoal-600 text-text-muted border border-white/[0.07] text-[10px] tracking-widest uppercase">
                  PREVIEW
                </span>
              )}
              {!score.semantic_available && (
                <span title="Semantic scoring unavailable" className="badge bg-amber-500/10 text-amber-400 border border-amber-500/20 text-[10px]">
                  <Info className="w-3 h-3" /> No semantic
                </span>
              )}
            </div>

            {/* Component scores */}
            <div className="space-y-2 mt-3">
              <ScoreBar label="Keyword Match" value={score.keyword_score} hex={colors.hex} />
              <ScoreBar label="Semantic" value={score.semantic_score} hex={colors.hex} disabled={!score.semantic_available} />
              <ScoreBar label="Experience" value={score.experience_score} hex={colors.hex} />
              <ScoreBar label="Section Quality" value={score.section_quality_score} hex={colors.hex} />
            </div>
          </div>
        </div>

        {/* Summary */}
        {score.summary_text && (
          <blockquote className="mt-4 pl-3 border-l-2 border-electric-500/40 italic text-text-secondary text-sm leading-relaxed">
            {score.summary_text}
          </blockquote>
        )}

        {/* Hiring recommendation */}
        {mode === "full" && score.hiring_recommendation && (
          <div className={`mt-4 flex items-center gap-2 px-4 py-3 rounded-lg ${colors.bg} border ${colors.border}`}>
            <Zap className={`w-4 h-4 flex-shrink-0 ${colors.text}`} />
            <span className={`text-sm font-medium ${colors.text}`}>{score.hiring_recommendation}</span>
          </div>
        )}
      </div>

      {/* Skills grid */}
      <div className="grid grid-cols-3 divide-x divide-white/[0.06] border-b border-white/[0.06]">
        <SkillColumn title="Matched" skills={score.matched_skills} type="matched" />
        <SkillColumn title="Missing" skills={score.missing_skills} type="missing" />
        <SkillColumn title="Extra" skills={score.extra_skills} type="extra" />
      </div>

      {/* Improvement tips */}
      {score.improvement_tips && score.improvement_tips.length > 0 && (
        <div className="p-4">
          <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
            Improvement Tips
          </h4>
          {(["high", "medium", "low"] as const).map((priority) => {
            const tips = grouped[priority] ?? [];
            if (!tips.length) return null;
            return (
              <div key={priority} className="mb-2">
                <button
                  onClick={() => setOpenPriority(openPriority === priority ? null : priority)}
                  className="w-full flex items-center justify-between px-3 py-2 rounded-lg hover:bg-charcoal-700 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <PriorityDot priority={priority} />
                    <span className="text-sm font-medium text-text-secondary capitalize">{priority} Priority</span>
                    <span className="text-xs text-text-muted">({tips.length})</span>
                  </div>
                  {openPriority === priority ? <ChevronUp className="w-4 h-4 text-text-muted" /> : <ChevronDown className="w-4 h-4 text-text-muted" />}
                </button>
                {openPriority === priority && (<AnimatePresence>
                  <motion.div
                    key="tips"
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.2 }}
                    className="mt-1 space-y-1 pl-3 overflow-hidden"
                  >
                    {tips.map((tip, i) => (
                      <div key={i} className="flex items-start gap-2 px-3 py-2 rounded-lg bg-charcoal-900/60 text-sm text-text-secondary">
                        <CategoryIcon category={tip.category} />
                        <span>{tip.tip}</span>
                      </div>
                    ))}
                  </motion.div>
                </AnimatePresence>)}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Sub-components
function ScoreBar({ label, value, hex, disabled }: { label: string; value: number; hex: string; disabled?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] text-text-muted w-28 flex-shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-charcoal-900 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-1000 ease-out"
          style={{ width: disabled ? "0%" : `${Math.round(value * 100)}%`, background: disabled ? "#2E3448" : hex, opacity: disabled ? 0.3 : 1 }}
        />
      </div>
      <span className="text-[11px] text-text-muted w-8 text-right">{disabled ? "N/A" : `${Math.round(value * 100)}%`}</span>
    </div>
  );
}

function SkillColumn({
  title,
  skills = [],
  type,
}: {
  title: string;
  skills?: string[];
  type: "matched" | "missing" | "extra";
}) {
  const colors = { matched: "text-emerald-400", missing: "text-red-400", extra: "text-text-muted" };
  const icons = {
    matched: <CheckCircle2 className="w-3 h-3 text-emerald-400" />,
    missing: <XCircle className="w-3 h-3 text-red-400" />,
    extra: <AlertCircle className="w-3 h-3 text-text-muted" />,
  };

  return (
    <div className="p-4">
      <div className={`flex items-center gap-1.5 mb-2 text-xs font-semibold uppercase tracking-wider ${colors[type]}`}>
        {icons[type]} {title} ({skills.length})
      </div>
      <div className="flex flex-wrap gap-1">
        {skills.slice(0, 8).map((s, i) => (
          <span key={i} className="text-xs px-2 py-0.5 rounded-full bg-charcoal-900 border border-white/[0.06] text-text-secondary">
            {s}
          </span>
        ))}
        {skills.length > 8 && (
          <span className="text-xs text-text-muted">+{skills.length - 8}</span>
        )}
      </div>
    </div>
  );
}

function PriorityDot({ priority }: { priority: string }) {
  const c = priority === "high" ? "bg-red-400" : priority === "medium" ? "bg-amber-400" : "bg-text-muted";
  return <span className={`w-2 h-2 rounded-full ${c}`} />;
}

function CategoryIcon({ category }: { category: string }) {
  const icons: Record<string, string> = {
    skills: "⚡", experience: "💼", education: "🎓", format: "📄",
  };
  return <span className="flex-shrink-0 text-xs">{icons[category] ?? "•"}</span>;
}

function groupTips(tips: AtsScore["improvement_tips"]) {
  return tips.reduce((acc, tip) => {
    const p = tip.priority;
    if (!acc[p]) acc[p] = [];
    acc[p].push(tip);
    return acc;
  }, {} as Record<string, typeof tips>);
}
