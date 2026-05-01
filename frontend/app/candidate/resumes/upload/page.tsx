"use client";
import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, queryKeys, getFriendlyError } from "@/lib/api/client";
import { useAuthStore } from "@/lib/store/authStore";
import { Upload, FileText, CheckCircle2, ArrowLeft, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { SkillBadge } from "@/components/shared";
import { formatFileSize } from "@/lib/utils/formatters";
import Link from "next/link";
import { Resume } from "@/lib/types";

const ALLOWED = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];
const MAX_BYTES = 10 * 1024 * 1024;

export default function ResumeUploadPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { userId } = useAuthStore();
  const [parsedResume, setParsedResume] = useState<Resume | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);

  const uploadMutation = useMutation({
    mutationFn: (file: File) => api.uploadResume(userId!, file),
    onSuccess: (res) => {
      toast.success("Resume uploaded and parsed!");
      setParsedResume(res.data);
      queryClient.invalidateQueries({ queryKey: queryKeys.candidateResumes(userId!) });
    },
    onError: (err) => toast.error(getFriendlyError(err)),
  });

  const onDrop = useCallback(
    (accepted: File[], rejected: any[]) => {
      if (rejected.length) {
        const err = rejected[0]?.errors?.[0];
        if (err?.code === "file-too-large") toast.error("File must be under 10 MB.");
        else if (err?.code === "file-invalid-type") toast.error("Only PDF and DOCX files accepted.");
        else toast.error("File rejected.");
        return;
      }
      const file = accepted[0];
      if (!ALLOWED.includes(file.type)) {
        toast.error("Only PDF and DOCX files accepted.");
        return;
      }
      if (file.size > MAX_BYTES) {
        toast.error("File must be under 10 MB.");
        return;
      }
      setParsedResume(null);
      setUploadProgress(0);
      uploadMutation.mutate(file);
    },
    [uploadMutation]
  );

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    },
    maxSize: MAX_BYTES,
    multiple: false,
    disabled: uploadMutation.isPending,
  });

  return (
    <div className="p-8 max-w-3xl mx-auto">
      <Link href="/candidate/resumes" className="inline-flex items-center gap-2 text-text-muted hover:text-text-primary text-sm mb-6 transition-colors">
        <ArrowLeft className="w-4 h-4" /> Back to Resumes
      </Link>

      <div className="mb-8">
        <h1 className="font-display text-3xl font-bold text-text-primary mb-1">Upload Resume</h1>
        <p className="text-text-secondary">Drop your resume and our AI will parse and analyze it instantly.</p>
      </div>

      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={`card p-12 border-2 border-dashed text-center cursor-pointer transition-all duration-200 mb-6 ${
          isDragReject
            ? "border-red-500/50 bg-red-500/5"
            : isDragActive
            ? "border-electric-500/60 bg-electric-500/5 glow-electric"
            : uploadMutation.isPending
            ? "border-charcoal-600 opacity-70 cursor-not-allowed"
            : "border-white/[0.1] hover:border-electric-500/40 hover:bg-electric-500/3"
        }`}
      >
        <input {...getInputProps()} />

        {uploadMutation.isPending ? (
          <div className="space-y-4">
            <Loader2 className="w-12 h-12 text-electric-400 mx-auto animate-spin" />
            <div>
              <p className="text-electric-400 font-semibold text-lg">Uploading & parsing...</p>
              <p className="text-text-muted text-sm mt-1">AI is extracting skills, experience, and education</p>
            </div>
            <div className="w-full max-w-xs mx-auto h-1.5 bg-charcoal-700 rounded-full overflow-hidden">
              <div className="h-full bg-electric-500 rounded-full animate-pulse" style={{ width: "60%" }} />
            </div>
          </div>
        ) : isDragReject ? (
          <div className="space-y-3">
            <X className="w-12 h-12 text-red-400 mx-auto" />
            <p className="text-red-400 font-medium">Only PDF and DOCX files accepted</p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className={`w-16 h-16 rounded-2xl mx-auto flex items-center justify-center transition-colors ${
              isDragActive ? "bg-electric-500/20" : "bg-charcoal-700"
            }`}>
              <Upload className={`w-8 h-8 transition-colors ${isDragActive ? "text-electric-400" : "text-text-muted"}`} />
            </div>
            <div>
              <p className="text-text-primary font-semibold text-lg">
                {isDragActive ? "Drop your resume here" : "Drag & drop your resume"}
              </p>
              <p className="text-text-muted text-sm mt-1">
                or <span className="text-electric-400 cursor-pointer">click to browse files</span>
              </p>
            </div>
            <div className="flex items-center justify-center gap-3 text-xs text-text-muted">
              <span className="flex items-center gap-1">
                <FileText className="w-3.5 h-3.5" /> PDF
              </span>
              <span>·</span>
              <span className="flex items-center gap-1">
                <FileText className="w-3.5 h-3.5" /> DOCX
              </span>
              <span>·</span>
              <span>Max 10 MB</span>
            </div>
          </div>
        )}
      </div>

      {/* Parse result */}
      {parsedResume && (
        <div className="space-y-4 animate-slide-up">
          {/* Status */}
          <div className={`card p-4 flex items-center gap-3 ${
            parsedResume.parse_status === "success"
              ? "border-emerald-500/25 bg-emerald-500/5"
              : parsedResume.parse_status === "failed"
              ? "border-red-500/25 bg-red-500/5"
              : "border-amber-500/25 bg-amber-500/5"
          }`}>
            <CheckCircle2 className={`w-5 h-5 flex-shrink-0 ${
              parsedResume.parse_status === "success" ? "text-emerald-400" :
              parsedResume.parse_status === "failed" ? "text-red-400" : "text-amber-400"
            }`} />
            <div className="flex-1">
              <div className="font-medium text-text-primary text-sm">{parsedResume.file_name}</div>
              <div className="text-xs text-text-muted">{formatFileSize(parsedResume.file_size_bytes)}</div>
            </div>
            <span className={`badge ${
              parsedResume.parse_status === "success" ? "badge-excellent" :
              parsedResume.parse_status === "failed" ? "badge-weak" : "badge-fair"
            } capitalize`}>
              {parsedResume.parse_status}
            </span>
          </div>

          {parsedResume.parse_status === "success" && (
            <>
              {/* Stats */}
              <div className="grid grid-cols-3 gap-3">
                <div className="card p-4 text-center">
                  <div className="font-display text-2xl font-bold text-electric-400">{parsedResume.skill_count}</div>
                  <div className="text-text-muted text-xs mt-1">Skills Found</div>
                </div>
                <div className="card p-4 text-center">
                  <div className="font-display text-2xl font-bold text-electric-400">
                    {parsedResume.total_experience_years.toFixed(1)}
                  </div>
                  <div className="text-text-muted text-xs mt-1">Years Experience</div>
                </div>
                <div className="card p-4 text-center">
                  <div className="font-display text-2xl font-bold text-electric-400">
                    {parsedResume.education.length}
                  </div>
                  <div className="text-text-muted text-xs mt-1">Education Entries</div>
                </div>
              </div>

              {/* Skills parsed */}
              {parsedResume.skills.length > 0 && (
                <div className="card p-5">
                  <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
                    Parsed Skills
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {parsedResume.skills.map((s, i) => (
                      <SkillBadge key={i} skill={s} variant="matched" />
                    ))}
                  </div>
                </div>
              )}

              {/* Experience */}
              {parsedResume.experience.length > 0 && (
                <div className="card p-5">
                  <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
                    Experience
                  </h3>
                  <div className="space-y-3">
                    {parsedResume.experience.map((exp, i) => (
                      <div key={i} className="flex items-start gap-3">
                        <div className="w-1.5 h-1.5 rounded-full bg-electric-500 mt-2 flex-shrink-0" />
                        <div>
                          <span className="font-medium text-sm text-text-primary">{exp.title}</span>
                          {exp.company && (
                            <span className="text-text-muted text-sm"> · {exp.company}</span>
                          )}
                          {exp.start_date && (
                            <div className="text-text-muted text-xs">
                              {exp.start_date} — {exp.end_date ?? "Present"}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Education */}
              {parsedResume.education.length > 0 && (
                <div className="card p-5">
                  <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-3">
                    Education
                  </h3>
                  <div className="space-y-2">
                    {parsedResume.education.map((edu, i) => (
                      <div key={i} className="flex items-start gap-3">
                        <div className="w-1.5 h-1.5 rounded-full bg-volt-400/60 mt-2 flex-shrink-0" />
                        <div className="text-sm">
                          <span className="font-medium text-text-primary">{edu.degree}</span>
                          {edu.field && <span className="text-text-muted"> in {edu.field}</span>}
                          {edu.institution && <div className="text-text-muted text-xs">{edu.institution}</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* CTA */}
              <div className="flex gap-3">
                <Link href="/candidate/jobs" className="btn-primary flex-1 text-center">
                  Browse Matching Jobs →
                </Link>
                <Link href="/candidate/resumes" className="btn-secondary flex-1 text-center">
                  View All Resumes
                </Link>
              </div>
            </>
          )}

          {parsedResume.parse_status === "failed" && (
            <div className="card p-5 text-center">
              <p className="text-red-400 text-sm mb-3">
                {parsedResume.parse_error_msg ?? "Failed to parse this file. Please try another."}
              </p>
              <p className="text-text-muted text-xs">Make sure the file is not password-protected or corrupted.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
