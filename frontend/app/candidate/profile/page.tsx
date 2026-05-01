"use client";
import { useEffect, useState, KeyboardEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { api, queryKeys, getFriendlyError, getClientToken } from "@/lib/api/client";
import { useAuthStore } from "@/lib/store/authStore";
import { toast } from "sonner";
import { Loader2, Save, X } from "lucide-react";

// ── Validation helpers ────────────────────────────────────────────────────────
const optionalUrl = z
  .string()
  .optional()
  .refine(
    (val) => !val || /^https?:\/\/.+\..+/.test(val),
    { message: "Must be a valid URL starting with http:// or https://" }
  );

const optionalPhone = z
  .string()
  .optional()
  .refine(
    (val) => !val || /^[\+]?[\d\s\-\(\)]{7,20}$/.test(val),
    { message: "Enter a valid phone number (7–20 digits)" }
  );

const schema = z.object({
  full_name: z
    .string()
    .min(2, "Name must be at least 2 characters")
    .max(100, "Name must be under 100 characters")
    .regex(/^[a-zA-Z\s'\-\.]+$/, "Name can only contain letters, spaces, hyphens, apostrophes and dots"),

  phone: optionalPhone,

  location: z
    .string()
    .max(100, "Location must be under 100 characters")
    .optional(),

  headline: z
    .string()
    .max(200, "Headline must be under 200 characters")
    .optional(),

  linkedin_url: optionalUrl,
  github_url: optionalUrl,
  portfolio_url: optionalUrl,

  open_to_work: z.boolean(),
});

type FormData = z.infer<typeof schema>;

// ── Tag input ─────────────────────────────────────────────────────────────────
function TagInput({
  label, values, onChange, placeholder, maxItems = 10, maxLength = 50,
}: {
  label: string;
  values: string[];
  onChange: (v: string[]) => void;
  placeholder: string;
  maxItems?: number;
  maxLength?: number;
}) {
  const [input, setInput] = useState("");
  const [error, setError] = useState("");

  const add = () => {
    const tag = input.trim();
    setError("");

    if (!tag) return;
    if (tag.length > maxLength) {
      setError(`Each item must be under ${maxLength} characters`);
      return;
    }
    if (values.includes(tag)) {
      setError("Already added");
      setInput("");
      return;
    }
    if (values.length >= maxItems) {
      setError(`Maximum ${maxItems} items allowed`);
      return;
    }
    if (!/^[a-zA-Z0-9\s\-\+\.\/]+$/.test(tag)) {
      setError("Only letters, numbers, spaces and - + . / allowed");
      return;
    }

    onChange([...values, tag]);
    setInput("");
  };

  const remove = (tag: string) => {
    onChange(values.filter((v) => v !== tag));
    setError("");
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
    if (e.key === "Backspace" && !input && values.length) remove(values[values.length - 1]);
  };

  return (
    <div>
      <label className="label">{label}</label>
      <div
        className="input min-h-[42px] flex flex-wrap gap-1.5 cursor-text"
        onClick={(e) => (e.currentTarget.querySelector("input") as HTMLInputElement)?.focus()}
      >
        {values.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-electric-500/15 text-electric-300 text-xs border border-electric-500/25"
          >
            {tag}
            <button type="button" onClick={() => remove(tag)} className="hover:text-red-400 transition-colors">
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
        <input
          value={input}
          onChange={(e) => { setInput(e.target.value); setError(""); }}
          onKeyDown={onKey}
          onBlur={add}
          placeholder={values.length === 0 ? placeholder : ""}
          className="bg-transparent outline-none text-sm text-text-primary placeholder:text-text-muted flex-1 min-w-[120px]"
        />
      </div>
      <div className="flex items-center justify-between mt-1">
        {error
          ? <p className="text-red-400 text-xs">{error}</p>
          : <p className="text-text-muted text-xs">Press Enter or comma to add</p>
        }
        <p className="text-text-muted text-xs">{values.length}/{maxItems}</p>
      </div>
    </div>
  );
}

// ── Field error helper ────────────────────────────────────────────────────────
function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="text-red-400 text-xs mt-1">{message}</p>;
}

// ── Profile Page ──────────────────────────────────────────────────────────────
export default function ProfilePage() {
  const queryClient = useQueryClient();
  const { userId, setAuth, accessToken, isRefreshing } = useAuthStore();

  const [preferredRoles,     setPreferredRoles]     = useState<string[]>([]);
  const [preferredLocations, setPreferredLocations] = useState<string[]>([]);
  const [rolesError,         setRolesError]         = useState("");
  const [locationsError,     setLocationsError]     = useState("");

 const { data, isLoading } = useQuery({
  queryKey: queryKeys.candidate(userId!),
  queryFn:  () => api.getCandidate(userId!),
  enabled:  !!userId && !isRefreshing && !!getClientToken(), 
});

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { open_to_work: true },
  });

  useEffect(() => {
    if (data?.data) {
      const c = data.data;
      reset({
        full_name:     c.full_name,
        phone:         c.phone         ?? "",
        location:      c.location      ?? "",
        headline:      c.headline      ?? "",
        linkedin_url:  c.linkedin_url  ?? "",
        github_url:    c.github_url    ?? "",
        portfolio_url: c.portfolio_url ?? "",
        open_to_work:  c.open_to_work,
      });
      setPreferredRoles(c.preferred_roles         ?? []);
      setPreferredLocations(c.preferred_locations  ?? []);
    }
  }, [data, reset]);

  const mutation = useMutation({
    mutationFn: (body: Partial<FormData> & {
      preferred_roles?: string[];
      preferred_locations?: string[];
    }) => api.updateCandidate(userId!, body),
    onSuccess: (res) => {
      toast.success("Profile updated!");
      setAuth("candidate", userId!, res.data.full_name, accessToken ?? "");
      queryClient.invalidateQueries({ queryKey: queryKeys.candidate(userId!) });
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  const onSubmit = (d: FormData) => {
    // Validate tag arrays before submitting
    let hasTagError = false;
    if (preferredRoles.length === 0) {
      setRolesError("Add at least one preferred role");
      hasTagError = true;
    }
    if (preferredLocations.length === 0) {
      setLocationsError("Add at least one preferred location");
      hasTagError = true;
    }
    if (hasTagError) return;

    mutation.mutate({
      ...d,
      // Sanitise optional URL fields — send undefined if empty so backend ignores them
      linkedin_url:  d.linkedin_url  || undefined,
      github_url:    d.github_url    || undefined,
      portfolio_url: d.portfolio_url || undefined,
      phone:         d.phone         || undefined,
      preferred_roles:     preferredRoles,
      preferred_locations: preferredLocations,
    });
  };

  // Live character counters
  const headlineValue = watch("headline") ?? "";
  const locationValue = watch("location") ?? "";

  return (
    <div className="p-8 max-w-2xl mx-auto">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-bold text-text-primary mb-1">Profile</h1>
        <p className="text-text-secondary">Manage your personal information and job preferences</p>
      </div>

      {isLoading ? (
        <div className="card p-6 space-y-4">
          {[1,2,3,4,5].map((i) => <div key={i} className="skeleton h-10 rounded-lg" />)}
        </div>
      ) : (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5" noValidate>

          {/* ── Personal Info ─────────────────────────────────────────────── */}
          <div className="card p-6 space-y-4">
            <h2 className="section-title">Personal Info</h2>

            <div className="flex items-center gap-4 pb-4 border-b border-white/[0.06]">
              <div className="w-14 h-14 rounded-2xl bg-electric-500/15 border border-electric-500/30 flex items-center justify-center">
                <span className="font-display text-xl font-bold text-electric-400">
                  {data?.data.full_name?.[0]?.toUpperCase()}
                </span>
              </div>
              <div>
                <div className="font-display font-semibold text-text-primary">{data?.data.full_name}</div>
                <div className="text-text-muted text-sm">{data?.data.email}</div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="label">Full Name *</label>
                <input
                  {...register("full_name")}
                  className={`input ${errors.full_name ? "border-red-500/50" : ""}`}
                  placeholder="Jane Smith"
                />
                <FieldError message={errors.full_name?.message} />
              </div>

              <div>
                <label className="label">Phone</label>
                <input
                  {...register("phone")}
                  className={`input ${errors.phone ? "border-red-500/50" : ""}`}
                  placeholder="+1 555 000 0000"
                  type="tel"
                />
                <FieldError message={errors.phone?.message} />
              </div>

              <div>
                <label className="label">
                  Location
                  <span className="text-text-muted text-xs ml-auto float-right">
                    {locationValue.length}/100
                  </span>
                </label>
                <input
                  {...register("location")}
                  className={`input ${errors.location ? "border-red-500/50" : ""}`}
                  placeholder="San Francisco, CA"
                  maxLength={100}
                />
                <FieldError message={errors.location?.message} />
              </div>

              <div className="col-span-2">
                <label className="label">
                  Headline
                  <span className="text-text-muted text-xs ml-auto float-right">
                    {headlineValue.length}/200
                  </span>
                </label>
                <input
                  {...register("headline")}
                  className={`input ${errors.headline ? "border-red-500/50" : ""}`}
                  placeholder="Senior Software Engineer · Open to remote"
                  maxLength={200}
                />
                <FieldError message={errors.headline?.message} />
              </div>
            </div>
          </div>

          {/* ── Links ────────────────────────────────────────────────────── */}
          <div className="card p-6 space-y-4">
            <h2 className="section-title">Links</h2>
            <p className="text-text-muted text-xs -mt-2">
              All URLs must start with <code className="text-electric-400">https://</code>
            </p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label">LinkedIn URL</label>
                <input
                  {...register("linkedin_url")}
                  className={`input ${errors.linkedin_url ? "border-red-500/50" : ""}`}
                  placeholder="https://linkedin.com/in/yourname"
                  type="url"
                />
                <FieldError message={errors.linkedin_url?.message} />
              </div>

              <div>
                <label className="label">GitHub URL</label>
                <input
                  {...register("github_url")}
                  className={`input ${errors.github_url ? "border-red-500/50" : ""}`}
                  placeholder="https://github.com/yourname"
                  type="url"
                />
                <FieldError message={errors.github_url?.message} />
              </div>

              <div className="col-span-2">
                <label className="label">Portfolio URL</label>
                <input
                  {...register("portfolio_url")}
                  className={`input ${errors.portfolio_url ? "border-red-500/50" : ""}`}
                  placeholder="https://yoursite.com"
                  type="url"
                />
                <FieldError message={errors.portfolio_url?.message} />
              </div>
            </div>
          </div>

          {/* ── Job Preferences ───────────────────────────────────────────── */}
          <div className="card p-6 space-y-4">
            <h2 className="section-title">Job Preferences</h2>

            <div>
              <TagInput
                label="Preferred Roles *"
                values={preferredRoles}
                onChange={(v) => { setPreferredRoles(v); setRolesError(""); }}
                placeholder="e.g. Software Engineer, Product Manager"
                maxItems={10}
                maxLength={50}
              />
              {rolesError && <p className="text-red-400 text-xs mt-1">{rolesError}</p>}
            </div>

            <div>
              <TagInput
                label="Preferred Locations *"
                values={preferredLocations}
                onChange={(v) => { setPreferredLocations(v); setLocationsError(""); }}
                placeholder="e.g. Remote, San Francisco, New York"
                maxItems={10}
                maxLength={50}
              />
              {locationsError && <p className="text-red-400 text-xs mt-1">{locationsError}</p>}
            </div>

            {/* Open to work toggle */}
            <div className="flex items-center justify-between p-4 rounded-xl bg-charcoal-900 border border-white/[0.06]">
              <div>
                <div className="font-medium text-text-primary text-sm">Open to Work</div>
                <div className="text-text-muted text-xs">Recruiters can find you in candidate search</div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" {...register("open_to_work")} className="sr-only peer" />
                <div className="w-11 h-6 bg-charcoal-600 rounded-full peer peer-checked:bg-electric-500/80 after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:after:translate-x-5" />
              </label>
            </div>
          </div>

          <button
            type="submit"
            disabled={mutation.isPending}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {mutation.isPending
              ? <Loader2 className="w-4 h-4 animate-spin" />
              : <Save className="w-4 h-4" />
            }
            Save Changes
          </button>
        </form>
      )}
    </div>
  );
}