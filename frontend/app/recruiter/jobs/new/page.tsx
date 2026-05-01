"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { api, queryKeys, getFriendlyError } from "@/lib/api/client";
import { useAuthStore } from "@/lib/store/authStore";
import { toast } from "sonner";
import { Plus, X, Loader2, ArrowLeft, Zap } from "lucide-react";

const schema = z.object({
  title: z.string().min(2, "Required"),
  company: z.string().min(1, "Required"),
  description: z.string().min(20, "Minimum 20 characters"),
  location: z.string().default("Remote"),
  job_type: z.enum(["full-time", "part-time", "contract", "internship", "freelance"]).default("full-time"),
  status: z.enum(["draft", "active", "paused", "closed"]).default("active"),
  experience_years: z.coerce.number().min(0).optional(),
  salary_min: z.coerce.number().min(0).optional(),
  salary_max: z.coerce.number().min(0).optional(),
  salary_currency: z.string().default("USD"),
});

type FormData = z.infer<typeof schema>;

export default function NewJobPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { userId } = useAuthStore();

  const [requiredSkills, setRequiredSkills] = useState<string[]>([]);
  const [niceSkills, setNiceSkills] = useState<string[]>([]);
  const [skillInput, setSkillInput] = useState("");
  const [niceInput, setNiceInput] = useState("");

  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { location: "Remote", job_type: "full-time", status: "active", salary_currency: "USD" },
  });

  const enhanceMutation = useMutation({
    mutationFn: (jobId: string) => api.enhanceJob(jobId),
    onSuccess: () => toast.success("Job enhanced with AI!"),
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  const mutation = useMutation({
    mutationFn: (body: FormData) =>
      api.createJob({ ...body, required_skills: requiredSkills, nice_to_have_skills: niceSkills, recruiter_id: userId! }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.recruiterJobs(userId!) });
      // Per master prompt: offer "Enhance with AI" after create
      toast.success("Job posted! Enhance it with AI for better matches?", {
        action: { label: "Enhance", onClick: () => enhanceMutation.mutate(res.data.id) },
        duration: 8000,
      });
      router.push(`/recruiter/jobs/${res.data.id}`);
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  const addSkill = (list: string[], setList: (v: string[]) => void, input: string, setInput: (v: string) => void) => {
    const trimmed = input.trim();
    if (trimmed && !list.includes(trimmed)) setList([...list, trimmed]);
    setInput("");
  };

  const removeSkill = (list: string[], setList: (v: string[]) => void, skill: string) =>
    setList(list.filter((s) => s !== skill));

  return (
    <div className="p-8 max-w-3xl mx-auto">
      <button onClick={() => router.back()} className="inline-flex items-center gap-2 text-text-muted hover:text-text-primary text-sm mb-6 transition-colors">
        <ArrowLeft className="w-4 h-4" /> Back
      </button>
      <h1 className="font-display text-3xl font-bold text-text-primary mb-1">Post a New Job</h1>
      <p className="text-text-secondary mb-8">Fill in the details to attract the best candidates.</p>

      <form onSubmit={handleSubmit((d) => mutation.mutate(d))} className="space-y-6">
        <div className="card p-6 space-y-5">
          <h2 className="font-display font-semibold text-text-primary text-lg border-b border-white/[0.06] pb-3">Basic Information</h2>
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="label">Job Title *</label>
              <input {...register("title")} className="input" placeholder="Senior Software Engineer" />
              {errors.title && <p className="text-red-400 text-xs mt-1">{errors.title.message}</p>}
            </div>
            <div>
              <label className="label">Company *</label>
              <input {...register("company")} className="input" placeholder="Acme Corp" />
              {errors.company && <p className="text-red-400 text-xs mt-1">{errors.company.message}</p>}
            </div>
            <div>
              <label className="label">Location</label>
              <input {...register("location")} className="input" placeholder="Remote, NYC, etc." />
            </div>
            <div>
              <label className="label">Job Type</label>
              <select {...register("job_type")} className="input">
                {["full-time","part-time","contract","internship","freelance"].map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Status</label>
              <select {...register("status")} className="input">
                {["active","draft","paused","closed"].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Experience (years)</label>
              <input {...register("experience_years")} type="number" className="input" placeholder="3" min={0} />
            </div>
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
        </div>

        <div className="card p-6 space-y-4">
          <h2 className="font-display font-semibold text-text-primary text-lg border-b border-white/[0.06] pb-3">Description</h2>
          <div>
            <label className="label">Job Description *</label>
            <textarea {...register("description")} className="input min-h-[160px] resize-y" placeholder="Describe the role, responsibilities, and what makes it exciting..." />
            {errors.description && <p className="text-red-400 text-xs mt-1">{errors.description.message}</p>}
          </div>
        </div>

        <div className="card p-6 space-y-4">
          <h2 className="font-display font-semibold text-text-primary text-lg border-b border-white/[0.06] pb-3">Skills</h2>

          <div>
            <label className="label">Required Skills</label>
            <div className="flex gap-2">
              <input
                className="input"
                placeholder="e.g. React, TypeScript..."
                value={skillInput}
                onChange={(e) => setSkillInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSkill(requiredSkills, setRequiredSkills, skillInput, setSkillInput); }}}
              />
              <button type="button" onClick={() => addSkill(requiredSkills, setRequiredSkills, skillInput, setSkillInput)} className="btn-secondary px-3">
                <Plus className="w-4 h-4" />
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {requiredSkills.map((s) => (
                <span key={s} className="badge badge-electric flex items-center gap-1">
                  {s}
                  <button type="button" onClick={() => removeSkill(requiredSkills, setRequiredSkills, s)}>
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
          </div>

          <div>
            <label className="label">Nice to Have</label>
            <div className="flex gap-2">
              <input
                className="input"
                placeholder="e.g. Docker, Kubernetes..."
                value={niceInput}
                onChange={(e) => setNiceInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSkill(niceSkills, setNiceSkills, niceInput, setNiceInput); }}}
              />
              <button type="button" onClick={() => addSkill(niceSkills, setNiceSkills, niceInput, setNiceInput)} className="btn-secondary px-3">
                <Plus className="w-4 h-4" />
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {niceSkills.map((s) => (
                <span key={s} className="badge badge-neutral flex items-center gap-1">
                  {s}
                  <button type="button" onClick={() => removeSkill(niceSkills, setNiceSkills, s)}>
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
          </div>
        </div>

        <button type="submit" disabled={mutation.isPending} className="btn-primary w-full flex items-center justify-center gap-2 py-3">
          {mutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
          Post Job
        </button>
      </form>
    </div>
  );
}
