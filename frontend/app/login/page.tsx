"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/store/authStore";
import { api, ApiError, getFriendlyError, setClientToken } from "@/lib/api/client";
import { Briefcase, User, ArrowRight, Loader2, Zap, Eye, EyeOff } from "lucide-react";
import { toast } from "sonner";
import { Candidate, Recruiter } from "@/lib/types";

type Role = "candidate" | "recruiter";
type Step = "role" | "credentials" | "register" | "change_password";

export default function LoginPage() {
  const router  = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);

  const [step,    setStep]    = useState<Step>("role");
  const [role,    setRole]    = useState<Role | null>(null);
  const [loading, setLoading] = useState(false);

  // Login form
  const [email,       setEmail]       = useState("");
  const [password,    setPassword]    = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [showPass,    setShowPass]    = useState(false);

  // Register form
  const [fullName,    setFullName]    = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [showRegPass, setShowRegPass] = useState(false);
  const [companyName, setCompanyName] = useState("");

  const handleRoleSelect = (r: Role) => {
    setRole(r);
    setStep("credentials");
  };

  // ── Helpers ────────────────────────────────────────────────────────────────
  // After a successful auth response, store everything and redirect
  const handleAuthSuccess = (
    accessToken: string,
    role: "candidate" | "recruiter",
    user: Candidate | Recruiter
  ) => {
    // 1. Store token in module-level memory (used by Axios interceptor)
    setClientToken(accessToken);
    // 2. Store identity in Zustand (persisted) + token in Zustand memory state
    setAuth(role, user.id, user.full_name, accessToken);
    // 3. Navigate to dashboard
    setTimeout(() => {
      router.push(role === "candidate"
        ? "/candidate/dashboard"
        : "/recruiter/dashboard"
      );
    }, 0);
    
  };

  // ── Login: POST /auth/login ────────────────────────────────────────────────
  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password || !role) return;
    setLoading(true);

    try {
      const res = await api.authLogin({
        email:    email.toLowerCase().trim(),
        password,
        role,
      });
      const { access_token, user } = res.data;
      toast.success("Welcome back!");
      handleAuthSuccess(access_token, role, user as Candidate | Recruiter);

    } catch (err) {
        if (err instanceof ApiError && err.code === "INVALID_CREDENTIALS") {
          toast.error("Invalid email or password.");
          // The "no account? Create one" link already exists in the JSX below the form.
          // That's the correct UX for this flow. No auto-redirect needed.
        } else {
          toast.error(getFriendlyError(err));
        }
    } finally {
      setLoading(false); 
    }
  }

  // ── Change Password ────────────────────────────────────────────────────────
  const handleChangePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password || !newPassword || !role) return;
    setLoading(true);

    try {
      // 1. Silent login to get the bearer token required by the backend
      const loginRes = await api.authLogin({
        email: email.toLowerCase().trim(),
        password, // old password
        role,
      });
      const { access_token, user } = loginRes.data;
      
      // 1.5 Inject token into the API client so the next request is authorized
      setClientToken(access_token);
      
      // 2. We now have an active token, so let's hit the change-password endpoint!
      // This happens securely within the same logical click so the user feels integrated.
      await api.authChangePassword({
        current_password: password,
        new_password: newPassword
      });

      toast.success("Password successfully changed!");
      
      // 3. Complete the login flow and boot them into dashboard normally
      handleAuthSuccess(access_token, role, user as Candidate | Recruiter);

    } catch (err) {
      if (err instanceof ApiError && err.code === "INVALID_CREDENTIALS") {
        toast.error("Invalid email or current password.");
      } else {
        toast.error(getFriendlyError(err));
      }
    } finally {
      setLoading(false);
    }
  };

  // ── Register: POST /auth/register/candidate|recruiter ─────────────────────
  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!role || !fullName || !email || !regPassword) return;
    setLoading(true);

    try {
      let res;
      if (role === "candidate") {
        res = await api.authRegisterCandidate({
          full_name: fullName,
          email:     email.toLowerCase().trim(),
          password:  regPassword,
        });
      } else {
        res = await api.authRegisterRecruiter({
          full_name:    fullName,
          email:        email.toLowerCase().trim(),
          password:     regPassword,
          company_name: companyName,
        });
      }
      const { access_token, user } = res.data;
      toast.success("Account created! Welcome aboard.");
      handleAuthSuccess(access_token, role, user as Candidate | Recruiter);

    } catch (err) {
      toast.error(getFriendlyError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-charcoal-950 flex items-center justify-center relative overflow-hidden">
      {/* Background effects */}
      <div className="absolute inset-0 bg-grid-pattern bg-grid opacity-40" />
      <div className="absolute inset-0 bg-glow-radial" />
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[600px] h-[300px] bg-electric-500/5 rounded-full blur-3xl" />

      <div className="relative z-10 w-full max-w-md px-4">
        {/* Logo */}
        <div className="text-center mb-10 animate-fade-in">
          <div className="inline-flex items-center gap-2 mb-4">
            <div className="w-10 h-10 rounded-xl bg-electric-500/15 border border-electric-500/30 flex items-center justify-center glow-electric">
              <Zap className="w-5 h-5 text-electric-400" />
            </div>
            <span className="font-display text-2xl font-bold text-text-primary">
              ATS<span className="text-electric-400">Pro</span>
            </span>
          </div>
          <p className="text-text-secondary text-sm">AI-powered Resume Intelligence Platform</p>
        </div>

        <div className="card p-8 animate-slide-up" style={{ animationDelay: "0.1s" }}>

          {/* ── Step: Role ──────────────────────────────────────────────────── */}
          {step === "role" && (
            <>
              <h1 className="font-display text-2xl font-bold text-text-primary mb-2">Welcome back</h1>
              <p className="text-text-secondary text-sm mb-8">Select your role to continue</p>
              <div className="grid grid-cols-2 gap-4">
                <RoleCard
                  icon={<User className="w-6 h-6" />}
                  label="Candidate"
                  description="Find jobs & track applications"
                  onClick={() => handleRoleSelect("candidate")}
                />
                <RoleCard
                  icon={<Briefcase className="w-6 h-6" />}
                  label="Recruiter"
                  description="Post jobs & rank applicants"
                  onClick={() => handleRoleSelect("recruiter")}
                />
              </div>
            </>
          )}

          {/* ── Step: Email + Password (Login) ──────────────────────────────── */}
          {step === "credentials" && (
            <>
              <button
                onClick={() => setStep("role")}
                className="text-text-muted hover:text-text-secondary text-xs mb-6 flex items-center gap-1 transition-colors"
              >
                ← Back
              </button>
              <h1 className="font-display text-2xl font-bold text-text-primary mb-2">
                Sign in as {role === "candidate" ? "Candidate" : "Recruiter"}
              </h1>
              <p className="text-text-secondary text-sm mb-8">
                Enter your credentials to continue
              </p>
              <form onSubmit={handleLoginSubmit} className="space-y-4">
                <div>
                  <label className="label">Email address</label>
                  <input
                    type="email"
                    className="input"
                    placeholder="you@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoFocus
                  />
                </div>
                <div>
                  <label className="label">Password</label>
                  <div className="relative">
                    <input
                      type={showPass ? "text" : "password"}
                      className="input pr-10"
                      placeholder="••••••••"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setShowPass((v) => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                    >
                      {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  <div className="flex justify-between items-center mt-2 px-1">
                    <span className="opacity-0">.</span>
                    <button
                      type="button"
                      className="text-text-muted hover:text-electric-400 text-xs transition-colors"
                      onClick={() => setStep("change_password")}
                    >
                      Change password?
                    </button>
                  </div>
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="btn-primary w-full flex items-center justify-center gap-2"
                >
                  {loading
                    ? <Loader2 className="w-4 h-4 animate-spin" />
                    : <>Sign in <ArrowRight className="w-4 h-4" /></>
                  }
                </button>
                <p className="text-center text-text-muted text-xs mt-2">
                  No account?{" "}
                  <button
                    type="button"
                    className="text-electric-400 hover:underline"
                    onClick={() => setStep("register")}
                  >
                    Create one
                  </button>
                </p>
              </form>
            </>
          )}

          {/* ── Step: Change Password ────────────────────────────────────────── */}
          {step === "change_password" && (
            <>
              <button
                onClick={() => setStep("credentials")}
                className="text-text-muted hover:text-text-secondary text-xs mb-6 flex items-center gap-1 transition-colors"
              >
                ← Back to sign in
              </button>
              <h1 className="font-display text-2xl font-bold text-text-primary mb-2">
                Update Password
              </h1>
              <p className="text-text-secondary text-sm mb-8">
                Verify your current {role === "candidate" ? "Candidate" : "Recruiter"} credentials to set a new password.
              </p>
              <form onSubmit={handleChangePasswordSubmit} className="space-y-4">
                <div>
                  <label className="label">Email address</label>
                  <input
                    type="email"
                    className="input"
                    placeholder="you@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoFocus
                  />
                </div>
                <div>
                  <label className="label">Current Password</label>
                  <div className="relative">
                    <input
                      type={showPass ? "text" : "password"}
                      className="input pr-10"
                      placeholder="••••••••"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setShowPass((v) => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                    >
                      {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                <div>
                  <label className="label">New Password</label>
                  <div className="relative">
                    <input
                      type={showPass ? "text" : "password"}
                      className="input pr-10"
                      placeholder="Min 8 chars, uppercase, number, symbol"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      required
                      minLength={8}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPass((v) => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                    >
                      {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="btn-primary w-full flex items-center justify-center gap-2 mt-4"
                >
                  {loading
                    ? <Loader2 className="w-4 h-4 animate-spin" />
                    : <>Secure Account <ArrowRight className="w-4 h-4" /></>
                  }
                </button>
              </form>
            </>
          )}

          {/* ── Step: Register ───────────────────────────────────────────────── */}
          {step === "register" && (
            <>
              <button
                onClick={() => setStep("credentials")}
                className="text-text-muted hover:text-text-secondary text-xs mb-6 flex items-center gap-1 transition-colors"
              >
                ← Back to sign in
              </button>
              <h1 className="font-display text-2xl font-bold text-text-primary mb-2">
                Create account
              </h1>
              <p className="text-text-secondary text-sm mb-8">
                Sign up as a {role === "candidate" ? "Candidate" : "Recruiter"}
              </p>
              <form onSubmit={handleRegister} className="space-y-4">
                <div>
                  <label className="label">Full name</label>
                  <input
                    className="input"
                    placeholder="Jane Smith"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    required
                    autoFocus
                  />
                </div>
                <div>
                  <label className="label">Email address</label>
                  <input
                    type="email"
                    className="input"
                    placeholder="you@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label className="label">Password</label>
                  <div className="relative">
                    <input
                      type={showRegPass ? "text" : "password"}
                      className="input pr-10"
                      placeholder="Min 8 chars, uppercase, number, symbol"
                      value={regPassword}
                      onChange={(e) => setRegPassword(e.target.value)}
                      required
                      minLength={8}
                    />
                    <button
                      type="button"
                      onClick={() => setShowRegPass((v) => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                    >
                      {showRegPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                  <p className="text-text-muted text-xs mt-1">
                    At least 8 characters with uppercase, number, and symbol
                  </p>
                </div>
                {role === "recruiter" && (
                  <div>
                    <label className="label">Company name</label>
                    <input
                      className="input"
                      placeholder="Acme Corp"
                      value={companyName}
                      onChange={(e) => setCompanyName(e.target.value)}
                      required
                    />
                  </div>
                )}
                <button
                  type="submit"
                  disabled={loading}
                  className="btn-primary w-full flex items-center justify-center gap-2"
                >
                  {loading
                    ? <Loader2 className="w-4 h-4 animate-spin" />
                    : <>Create account <ArrowRight className="w-4 h-4" /></>
                  }
                </button>
              </form>
            </>
          )}
        </div>

        <p className="text-center text-text-muted text-xs mt-6">
          AI-powered by Groq · Semantic matching · Real-time scoring
        </p>
      </div>
    </div>
  );
}

function RoleCard({ icon, label, description, onClick }: {
  icon: React.ReactNode; label: string; description: string; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="group flex flex-col items-center gap-3 p-5 rounded-xl bg-charcoal-900
                 border border-white/[0.07] hover:border-electric-500/40 hover:bg-charcoal-800
                 transition-all duration-200 text-center"
    >
      <div className="w-12 h-12 rounded-xl bg-electric-500/10 flex items-center justify-center
                      text-electric-400 group-hover:bg-electric-500/20 transition-colors">
        {icon}
      </div>
      <div>
        <div className="font-display font-semibold text-text-primary text-sm">{label}</div>
        <div className="text-text-muted text-xs mt-0.5">{description}</div>
      </div>
    </button>
  );
}
