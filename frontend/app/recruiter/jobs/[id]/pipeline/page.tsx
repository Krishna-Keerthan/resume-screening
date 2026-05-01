"use client";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, queryKeys, getFriendlyError } from "@/lib/api/client";
import { AtsScoreCard } from "@/components/shared/AtsScoreCard";
import { StageBadge, ScoreBadge } from "@/components/shared";
import { formatRelativeDate } from "@/lib/utils/formatters";
import { ArrowLeft, X, Save, Loader2, User, Users, Zap } from "lucide-react";
import { toast } from "sonner";
import Link from "next/link";
import { useState, useEffect } from "react";
import { Application, ApplicationStage } from "@/lib/types";
import { createPortal } from "react-dom";

// Add this map at the top of the file
const STAGE_TRANSITIONS: Record<ApplicationStage, ApplicationStage[]> = {
  applied:      ["reviewed", "rejected", "withdrawn"],
  reviewed:     ["shortlisted", "rejected", "withdrawn"],
  shortlisted:  ["interviewing", "rejected", "withdrawn"],
  interviewing: ["offered", "rejected", "withdrawn"],
  offered:      ["hired", "rejected", "withdrawn"],
  hired:        [],
  rejected:     [],
  withdrawn:    [],
};

const COLUMNS: { stage: ApplicationStage; label: string }[] = [
  { stage: "applied",      label: "Applied"      },
  { stage: "reviewed",     label: "Reviewed"     },
  { stage: "shortlisted",  label: "Shortlisted"  },
  { stage: "interviewing", label: "Interviewing" },
  { stage: "offered",      label: "Offered"      },
  { stage: "hired",        label: "Hired"        },
  { stage: "rejected",     label: "Rejected"     },
];

// ── Portal wrapper — mounts children into document.body ──────────────────────
function Portal({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);
  if (!mounted) return null;
  return createPortal(children, document.body);
}

export default function ApplicantsKanbanPage() {
  const { id }         = useParams<{ id: string }>();
  const queryClient    = useQueryClient();
  const [selectedApp,     setSelectedApp]    = useState<Application | null>(null);
  const [stageModal,      setStageModal]     = useState<Application | null>(null);
  const [newStage,        setNewStage]       = useState<ApplicationStage>("reviewed");
  const [notes,           setNotes]          = useState("");
  const [rejectionReason, setRejectionReason] = useState("");

  const [aiSummaries, setAiSummaries] = useState<Record<string, { summary: string; recommendation: string }>>({});
  const [loadingSummary, setLoadingSummary] = useState<string | null>(null);

  const handleGetAiSummary = async (applicationId: string) => {
    if (aiSummaries[applicationId]) return;
    setLoadingSummary(applicationId);
    try {
      const res = await api.getApplicationAiSummary(applicationId);
      setAiSummaries((prev) => ({ ...prev, [applicationId]: res.data }));
    } catch { toast.error("Could not generate summary."); }
    finally { setLoadingSummary(null); }
  };


  // Lock body scroll when any modal is open
  useEffect(() => {
    if (selectedApp || stageModal) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [selectedApp, stageModal]);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.applications({ job_id: id }),
    queryFn:  () => api.listApplications({ job_id: id, limit: 100 }),
  });

  const { data: jobData } = useQuery({
    queryKey: queryKeys.job(id),
    queryFn:  () => api.getJob(id),
  });

  const stageMutation = useMutation({
  mutationFn: ({ appId, stage, recruiter_notes, rejection_reason }: {
    appId: string; stage: ApplicationStage; recruiter_notes?: string; rejection_reason?: string;
  }) => api.updateApplicationStage(appId, { stage, recruiter_notes, rejection_reason }),
  onMutate: async ({ appId, stage, recruiter_notes, rejection_reason }) => {
    await queryClient.cancelQueries({ queryKey: queryKeys.applications({ job_id: id }) });
    const prev = queryClient.getQueryData(queryKeys.applications({ job_id: id }));
    queryClient.setQueryData(queryKeys.applications({ job_id: id }), (old: any) => ({
      ...old,
      data: old?.data?.map((a: Application) =>
        a.id === appId
          ? {
              ...a,
              stage,
              recruiter_notes:  recruiter_notes  ?? a.recruiter_notes,   // ← add
              rejection_reason: rejection_reason ?? a.rejection_reason,  // ← add
            }
          : a
      ),
    }));
    return { prev };
  },
  onError: (err, _, ctx) => {
    if (ctx?.prev) queryClient.setQueryData(queryKeys.applications({ job_id: id }), ctx.prev);
    toast.error(getFriendlyError(err));
  },
  onSuccess: (res) => {
    // ← Refetch to get server-confirmed data instead of just closing
    queryClient.invalidateQueries({ queryKey: queryKeys.applications({ job_id: id }) });
    toast.success("Stage updated!");
    setStageModal(null);
    setSelectedApp(null);
    setNotes("");
    setRejectionReason("");
  },
});

  const applications = data?.data ?? [];
  const getAppsForStage = (stage: ApplicationStage) =>
    applications.filter((a) => a.stage === stage);

  const openStageModal = (app: Application) => {
  const validNext = STAGE_TRANSITIONS[app.stage] ?? [];
  setNewStage(validNext[0] ?? app.stage); // ← default to first valid stage
  setNotes("");
  setRejectionReason("");
  setStageModal(app);
};

  const isTerminalStage = (stage: ApplicationStage) =>
    stage === "hired" || stage === "rejected";

  const recColors: Record<string, string> = {
  strong_yes: "bg-emerald-500/10 border-emerald-500/20 text-emerald-400",
  yes:        "bg-electric-500/10 border-electric-500/20 text-electric-400",
  maybe:      "bg-amber-500/10 border-amber-500/20 text-amber-400",
  no:         "bg-red-500/10 border-red-500/20 text-red-400",
  };

  return (
    <div className="flex flex-col" style={{ height: "calc(100vh - 0px)" }}>

      {/* Header */}
      <div className="flex items-center gap-4 px-6 pt-6 pb-4 flex-shrink-0 bg-charcoal-950 border-b border-white/[0.06]">
        <Link
          href={`/recruiter/jobs/${id}`}
          className="inline-flex items-center gap-1.5 text-text-muted hover:text-text-primary text-sm transition-colors flex-shrink-0"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to Job</span>
        </Link>
        <div className="w-px h-4 bg-white/[0.1]" />
        <div className="min-w-0">
          <h1 className="font-display text-xl font-bold text-text-primary truncate">
            Pipeline — {jobData?.data?.title ?? "Loading…"}
          </h1>
        </div>
        <div className="ml-auto flex items-center gap-1.5 flex-shrink-0 px-3 py-1 rounded-full bg-charcoal-800 border border-white/[0.07]">
          <Users className="w-3.5 h-3.5 text-text-muted" />
          <span className="text-sm text-text-secondary">
            {isLoading ? "—" : applications.length} applicant{applications.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {/* Kanban board — independent scroll, no height clash */}
      <div className="flex-1 overflow-x-auto overflow-y-auto px-6 py-6">
        {isLoading ? (
          <div className="flex gap-3">
            {COLUMNS.map((_, i) => (
              <div key={i} className="flex-shrink-0 w-56">
                <div className="h-10 skeleton rounded-lg mb-3" />
                <div className="space-y-2">
                  {[1,2].map((j) => <div key={j} className="card h-24 skeleton" />)}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex gap-3 items-start" style={{ minWidth: "max-content" }}>
            {COLUMNS.map(({ stage, label }) => (
              <KanbanColumn
                key={stage}
                stage={stage}
                label={label}
                apps={getAppsForStage(stage)}
                isTerminal={isTerminalStage(stage)}
                onCardClick={setSelectedApp}
                onMoveClick={isTerminalStage(stage) ? () => {} : openStageModal}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Application detail modal — rendered via Portal to avoid layout clash */}
      {selectedApp && (
        <Portal>
          <div
            className="fixed inset-0 flex items-center justify-center z-[100]"
            onClick={() => setSelectedApp(null)}
          >
            {/* Backdrop */}
            <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />

            {/* Modal box */}
            <div
              className="relative w-full max-w-lg mx-4 bg-charcoal-900 border border-white/[0.08] rounded-2xl shadow-2xl overflow-hidden max-h-[85vh] flex flex-col"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Modal header */}
              <div className="p-5 border-b border-white/[0.06] flex items-center justify-between flex-shrink-0">
                <div>
                  <h2 className="font-display font-semibold text-text-primary">
                    {selectedApp.candidate?.full_name ?? "Applicant"}
                  </h2>
                  <div className="flex items-center gap-2 mt-1">
                    <StageBadge stage={selectedApp.stage} />
                    <span className="text-text-muted text-xs">
                      {formatRelativeDate(selectedApp.applied_at)}
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => setSelectedApp(null)}
                  className="p-2 rounded-lg hover:bg-charcoal-700 transition-colors"
                >
                  <X className="w-4 h-4 text-text-muted" />
                </button>
              </div>

              

              {/* Modal body — scrollable */}
              <div className="flex-1 overflow-y-auto p-5 space-y-4">
                  {selectedApp && (
                    // In modal body:
                    <div className="space-y-3">
                      {/* AI Summary */}
                      {aiSummaries[selectedApp.id] ? (
                        <div className={`p-3 rounded-xl border text-sm ${
                          recColors[aiSummaries[selectedApp.id].recommendation] ?? recColors.maybe
                        }`}>
                          <p className="font-semibold text-xs uppercase tracking-wider mb-1">
                            AI Hiring Summary
                          </p>
                          <p className="leading-relaxed">{aiSummaries[selectedApp.id].summary}</p>
                        </div>
                      ) : (
                        <button
                          onClick={() => handleGetAiSummary(selectedApp.id)}
                          disabled={loadingSummary === selectedApp.id}
                          className="btn-ghost text-xs flex items-center gap-1.5 text-electric-400 w-full justify-center"
                        >
                          {loadingSummary === selectedApp.id
                            ? <Loader2 className="w-3 h-3 animate-spin" />
                            : <Zap className="w-3 h-3" />
                          }
                          Generate AI Hiring Summary
                        </button>
                      )}

                      {/* Existing ATS score card */}
                      {selectedApp.ats_score
                        ? <AtsScoreCard score={selectedApp.ats_score} mode="full" />
                        : <div className="card p-6 text-center text-text-muted text-sm">No ATS score available.</div>
                      }
                    </div>
                  )}

                  {/* ← Add recruiter notes display */}
                    {selectedApp.recruiter_notes && (
                      <div className="card p-4 space-y-1">
                        <p className="text-xs text-text-muted uppercase tracking-wider font-semibold">
                          Recruiter Notes
                        </p>
                        <p className="text-sm text-text-secondary leading-relaxed">
                          {selectedApp.recruiter_notes}
                        </p>
                      </div>
                    )}

                  {/* ← Add rejection reason display */}
                    {selectedApp.rejection_reason && (
                      <div className="card p-4 space-y-1 border-red-500/20">
                        <p className="text-xs text-red-400 uppercase tracking-wider font-semibold">
                          Rejection Reason
                        </p>
                        <p className="text-sm text-text-secondary leading-relaxed">
                          {selectedApp.rejection_reason}
                        </p>
                      </div>
                  )}
              </div>

              

              {/* Modal footer */}
              {!isTerminalStage(selectedApp.stage) && (
                <div className="p-5 border-t border-white/[0.06] flex-shrink-0">
                  <button
                    onClick={() => { setSelectedApp(null); openStageModal(selectedApp); }}
                    className="btn-primary w-full"
                  >
                    Update Stage
                  </button>
                </div>
              )}
            </div>
          </div>
        </Portal>
      )}

      {/* ── Stage update modal — also via Portal */}
      {stageModal && (
        <Portal>
          <div
            className="fixed inset-0 flex items-center justify-center z-[100]"
            onClick={() => setStageModal(null)}
          >
            <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
            <div
              className="relative w-full max-w-md mx-4 bg-charcoal-900 border border-white/[0.08] rounded-2xl shadow-2xl p-6 space-y-4 max-h-[85vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between">
                <h2 className="font-display font-semibold text-text-primary">Update Stage</h2>
                <button
                  onClick={() => setStageModal(null)}
                  className="p-2 rounded-lg hover:bg-charcoal-700 transition-colors"
                >
                  <X className="w-4 h-4 text-text-muted" />
                </button>
              </div>

              <p className="text-text-muted text-sm">
                {stageModal.candidate?.full_name ?? "Applicant"}
                <span className="ml-2"><StageBadge stage={stageModal.stage} /></span>
              </p>

              <div>
                <label className="label">New Stage</label>
                <select
                  className="input"
                  value={newStage}
                  onChange={(e) => setNewStage(e.target.value as ApplicationStage)}
                >
                  {(STAGE_TRANSITIONS[stageModal.stage] ?? []).length === 0 ? (
                    <option disabled>No valid transitions</option>
                  ) : (
                    STAGE_TRANSITIONS[stageModal.stage].map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))
                  )}
                </select>
              </div>

              <div>
                <label className="label">Recruiter Notes (optional)</label>
                <textarea
                  className="input min-h-[80px]"
                  placeholder="Add notes for your team..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </div>

              {newStage === "rejected" && (
                <div>
                  <label className="label">Rejection Reason *</label>
                  <input
                    className="input"
                    placeholder="Not enough experience..."
                    value={rejectionReason}
                    onChange={(e) => setRejectionReason(e.target.value)}
                  />
                </div>
              )}

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => setStageModal(null)}
                  className="btn-secondary flex-1"
                >
                  Cancel
                </button>
                <button
                  onClick={() => stageMutation.mutate({
                    appId:            stageModal.id,
                    stage:            newStage,
                    recruiter_notes:  notes || undefined,
                    rejection_reason: newStage === "rejected" ? rejectionReason : undefined,
                  })}
                  disabled={
                    stageMutation.isPending ||
                    (newStage === "rejected" && !rejectionReason)
                  }
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {stageMutation.isPending
                    ? <Loader2 className="w-4 h-4 animate-spin" />
                    : <Save className="w-4 h-4" />
                  }
                  Save
                </button>
              </div>
            </div>
          </div>
        </Portal>
      )}
    </div>
  );
}

// ── KanbanColumn ──────────────────────────────────────────────────────────────
const HEADER_COLORS: Record<string, string> = {
  applied:      "bg-blue-500/10     text-blue-400    border-blue-500/20",
  reviewed:     "bg-electric-500/10 text-electric-400 border-electric-500/20",
  shortlisted:  "bg-purple-500/10   text-purple-400  border-purple-500/20",
  interviewing: "bg-amber-500/10    text-amber-400   border-amber-500/20",
  offered:      "bg-emerald-500/10  text-emerald-400 border-emerald-500/20",
  hired:        "bg-emerald-500/15  text-emerald-300 border-emerald-500/30",
  rejected:     "bg-red-500/10      text-red-400     border-red-500/20",
};

function KanbanColumn({ stage, label, apps, onCardClick, onMoveClick, isTerminal }: {
  stage:       ApplicationStage;
  label:       string;
  apps:        Application[];
  onCardClick: (a: Application) => void;
  onMoveClick: (a: Application) => void;
  isTerminal:  boolean;
}) {
  return (
    <div className="flex flex-col w-56 flex-shrink-0">
      <div className={`flex items-center justify-between px-3 py-2 rounded-lg border mb-2 ${HEADER_COLORS[stage] ?? "bg-charcoal-700 text-text-secondary border-white/[0.07]"}`}>
        <span className="text-sm font-semibold capitalize">{label}</span>
        <span className="text-xs font-bold opacity-80 bg-black/20 px-1.5 py-0.5 rounded-full min-w-[20px] text-center">
          {apps.length}
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {apps.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 px-3 rounded-xl border border-dashed border-white/[0.06] text-center">
            <div className="w-8 h-8 rounded-full bg-charcoal-800 flex items-center justify-center mb-2">
              <User className="w-3.5 h-3.5 text-text-muted opacity-40" />
            </div>
            <p className="text-[11px] text-text-muted opacity-50">No candidates</p>
          </div>
        ) : (
          apps.map((app) => (
            <ApplicantCard
              key={app.id}
              app={app}
              onClick={() => onCardClick(app)}
              onMove={() => onMoveClick(app)}
              isTerminal={isTerminal}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ── ApplicantCard ─────────────────────────────────────────────────────────────
function ApplicantCard({ app, onClick, onMove, isTerminal }: {
  app:        Application;
  onClick:    () => void;
  onMove:     () => void;
  isTerminal: boolean;
}) {
  return (
    <div className="card-hover p-3 cursor-pointer group" onClick={onClick}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-7 h-7 rounded-full bg-charcoal-600 flex items-center justify-center flex-shrink-0">
            <User className="w-3.5 h-3.5 text-text-muted" />
          </div>
          <span className="text-sm font-medium text-text-primary truncate">
            {app.candidate?.full_name ?? "Candidate"}
          </span>
        </div>
        {app.ats_score && (
          <ScoreBadge score={app.ats_score.final_score} label={app.ats_score.score_label} />
        )}
      </div>

      {app.ats_score && (
        <div className="flex flex-wrap gap-1 mb-2">
          {app.ats_score.matched_skills.slice(0, 3).map((s, i) => (
            <span key={i} className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              {s}
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between">
        <span className="text-[10px] text-text-muted">{formatRelativeDate(app.applied_at)}</span>
        {!isTerminal && (
          <button
            onClick={(e) => { e.stopPropagation(); onMove(); }}
            className="text-[10px] text-electric-400 hover:text-electric-300 opacity-0 group-hover:opacity-100 transition-opacity px-2 py-0.5 rounded bg-electric-500/10"
          >
            Move →
          </button>
        )}
      </div>
    </div>
  );
}

