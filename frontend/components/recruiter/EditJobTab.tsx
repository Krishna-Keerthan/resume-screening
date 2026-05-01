"use client";
import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { api, queryKeys, getFriendlyError } from "@/lib/api/client";
import { useAuthStore } from "@/lib/store/authStore";
import { Job } from "@/lib/types";
import { toast } from "sonner";
import { Plus, X, Loader2, Save, Zap, RotateCcw } from "lucide-react";

const schema = z.object({
  title:            z.string().min(2, "Required"),
  company:          z.string().min(1, "Required"),
  description:      z.string().min(20, "Minimum 20 characters"),
  location:         z.string().default("Remote"),
  job_type:         z.enum(["full-time", "part-time", "contract", "internship", "freelance"]).default("full-time"),
  status:           z.enum(["draft", "active", "paused", "closed"]).default("active"),
  experience_years: z.coerce.number().min(0).optional(),
  salary_min:       z.coerce.number().min(0).optional(),
  salary_max:       z.coerce.number().min(0).optional(),
  salary_currency:  z.string().default("USD"),
});

type FormData = z.infer<typeof schema>;

interface EditJobTabProps {
  job: Job;
}

export function EditJobTab({ job }: EditJobTabProps) {
  const queryClient       = useQueryClient();
  const { userId }        = useAuthStore();

  const [requiredSkills, setRequiredSkills] = useState<string[]>([]);
  const [niceSkills,     setNiceSkills]     = useState<string[]>([]);
  const [skillInput,     setSkillInput]     = useState("");
  const [niceInput,      setNiceInput]      = useState("");

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isDirty: formIsDirty },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  // ── Populate form from the job prop ──────────────────────────────────────
  // This runs whenever the parent re-fetches the job (e.g. after AI enhance),
  // keeping the form always in sync with the latest server state.
  useEffect(() => {
    reset({
      title:            job.title            ?? "",
      company:          job.company          ?? "",
      description:      job.description      ?? "",
      location:         job.location         ?? "Remote",
      job_type:         job.job_type         ?? "full-time",
      status:           job.status           ?? "active",
      experience_years: job.experience_years ?? undefined,
      salary_min:       job.salary_min       ?? undefined,
      salary_max:       job.salary_max       ?? undefined,
      salary_currency:  job.salary_currency  ?? "USD",
    });
    setRequiredSkills(job.required_skills     ?? []);
    setNiceSkills(    job.nice_to_have_skills ?? []);
  }, [job, reset]);

  // ── Dirty tracking includes skills (outside RHF) ─────────────────────────
  const skillsDirty =
    JSON.stringify(requiredSkills) !== JSON.stringify(job.required_skills     ?? []) ||
    JSON.stringify(niceSkills)     !== JSON.stringify(job.nice_to_have_skills ?? []);

  const hasChanges = formIsDirty || skillsDirty;

  // ── Save ──────────────────────────────────────────────────────────────────
  const saveMutation = useMutation({
    mutationFn: (body: FormData) =>
      api.updateJob(job.id, {
        ...body,
        required_skills:     requiredSkills,
        nice_to_have_skills: niceSkills,
      }),
    onSuccess: () => {
      // Invalidate so the details tab and recruiter job list both refresh
      queryClient.invalidateQueries({ queryKey: queryKeys.job(job.id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.recruiterJobs(userId!) });
      toast.success("Job updated successfully.");
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  // ── AI Enhance ────────────────────────────────────────────────────────────
  const enhanceMutation = useMutation({
    mutationFn: () => api.enhanceJob(job.id),
    onSuccess: () => {
      // Invalidating the job query causes the parent to re-fetch,
      // which updates the `job` prop, which triggers the useEffect above,
      // which resets the form with the AI-enhanced content automatically.
      queryClient.invalidateQueries({ queryKey: queryKeys.job(job.id) });
      toast.success("Job enhanced with AI — form updated with new content.");
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  // ── Discard ───────────────────────────────────────────────────────────────
  const handleDiscard = () => {
    reset();
    setRequiredSkills(job.required_skills     ?? []);
    setNiceSkills(    job.nice_to_have_skills ?? []);
  };

  // ── Skill helpers ─────────────────────────────────────────────────────────
  const addSkill = (
    list:     string[], setList:  (v: string[]) => void,
    input:    string,   setInput: (v: string)   => void,
  ) => {
    const t = input.trim();
    if (t && !list.includes(t)) setList([...list, t]);
    setInput("");
  };

  const removeSkill = (list: string[], setList: (v: string[]) => void, skill: string) =>
    setList(list.filter((s) => s !== skill));

  return (
    <form onSubmit={handleSubmit((d) => saveMutation.mutate(d))} className="space-y-6">

      {/* ── Toolbar ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {hasChanges && (
            <>
              <span className="text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 px-2.5 py-1 rounded-full">
                Unsaved changes
              </span>
              <button
                type="button"
                onClick={handleDiscard}
                className="inline-flex items-center gap-1.5 text-xs text-text-muted hover:text-text-primary transition-colors"
              >
                <RotateCcw className="w-3 h-3" />
                Discard
              </button>
            </>
          )}
        </div>
        <button
          type="button"
          onClick={() => enhanceMutation.mutate()}
          disabled={enhanceMutation.isPending}
          className="btn-secondary inline-flex items-center gap-2 text-sm"
        >
          {enhanceMutation.isPending
            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : <Zap className="w-3.5 h-3.5 text-electric-400" />
          }
          Enhance with AI
        </button>
      </div>

      {/* ── Basic Info ───────────────────────────────────────────────────── */}
      <div className="card p-6 space-y-4">
        <SectionTitle>Basic Information</SectionTitle>
        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <label className="label">Job Title *</label>
            <input {...register("title")} className="input" placeholder="Senior Software Engineer" />
            {errors.title && <FieldError msg={errors.title.message!} />}
          </div>
          <div>
            <label className="label">Company *</label>
            <input {...register("company")} className="input" placeholder="Acme Corp" />
            {errors.company && <FieldError msg={errors.company.message!} />}
          </div>
          <div>
            <label className="label">Location</label>
            <input {...register("location")} className="input" placeholder="Remote, NYC, etc." />
          </div>
          <div>
            <label className="label">Job Type</label>
            <select {...register("job_type")} className="input">
              {["full-time","part-time","contract","internship","freelance"].map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Status</label>
            <select {...register("status")} className="input">
              {["active","draft","paused","closed"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* ── Compensation ─────────────────────────────────────────────────── */}
      <div className="card p-6 space-y-4">
        <SectionTitle>Compensation & Experience</SectionTitle>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="label">Currency</label>
            <input {...register("salary_currency")} className="input" placeholder="USD" maxLength={3} />
          </div>
          <div>
            <label className="label">Salary Min</label>
            <input {...register("salary_min")} type="number" className="input" placeholder="80000" min={0} />
          </div>
          <div>
            <label className="label">Salary Max</label>
            <input {...register("salary_max")} type="number" className="input" placeholder="120000" min={0} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Experience (years)</label>
            <input {...register("experience_years")} type="number" className="input" placeholder="3" min={0} />
          </div>
        </div>
      </div>

      {/* ── Description ──────────────────────────────────────────────────── */}
      <div className="card p-6 space-y-4">
        <SectionTitle>Job Description *</SectionTitle>
        <textarea
          {...register("description")}
          className="input min-h-[200px] resize-y"
          placeholder="Describe the role, responsibilities, and what makes it exciting..."
        />
        {errors.description && <FieldError msg={errors.description.message!} />}
      </div>

      {/* ── Skills ───────────────────────────────────────────────────────── */}
      <div className="card p-6 space-y-5">
        <SectionTitle>Skills</SectionTitle>
        <SkillInput
          label="Required Skills"
          skills={requiredSkills}
          input={skillInput}
          onInputChange={setSkillInput}
          onAdd={() => addSkill(requiredSkills, setRequiredSkills, skillInput, setSkillInput)}
          onRemove={(s) => removeSkill(requiredSkills, setRequiredSkills, s)}
          badgeClass="badge badge-electric"
        />
        <SkillInput
          label="Nice to Have"
          skills={niceSkills}
          input={niceInput}
          onInputChange={setNiceInput}
          onAdd={() => addSkill(niceSkills, setNiceSkills, niceInput, setNiceInput)}
          onRemove={(s) => removeSkill(niceSkills, setNiceSkills, s)}
          badgeClass="badge badge-neutral"
        />
      </div>

      {/* ── Save button ───────────────────────────────────────────────────── */}
      <button
        type="submit"
        disabled={saveMutation.isPending || !hasChanges}
        className="btn-primary w-full flex items-center justify-center gap-2 py-3"
      >
        {saveMutation.isPending
          ? <Loader2 className="w-4 h-4 animate-spin" />
          : <Save className="w-4 h-4" />
        }
        {saveMutation.isPending ? "Saving..." : "Save Changes"}
      </button>

    </form>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="font-display font-semibold text-text-primary border-b border-white/[0.06] pb-3">
      {children}
    </h3>
  );
}

function FieldError({ msg }: { msg: string }) {
  return <p className="text-red-400 text-xs mt-1">{msg}</p>;
}

function SkillInput({
  label, skills, input, onInputChange, onAdd, onRemove, badgeClass,
}: {
  label:         string;
  skills:        string[];
  input:         string;
  onInputChange: (v: string) => void;
  onAdd:         () => void;
  onRemove:      (s: string) => void;
  badgeClass:    string;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <div className="flex gap-2">
        <input
          className="input"
          placeholder="Type a skill and press Enter..."
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onAdd(); } }}
        />
        <button type="button" onClick={onAdd} className="btn-secondary px-3">
          <Plus className="w-4 h-4" />
        </button>
      </div>
      {skills.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {skills.map((s) => (
            <span key={s} className={`${badgeClass} flex items-center gap-1`}>
              {s}
              <button
                type="button"
                onClick={() => onRemove(s)}
                className="hover:text-red-400 transition-colors"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}