"use client";
import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/lib/store/authStore";
import { useLogout } from "@/lib/hooks/useLogout";
import { useQuery } from "@tanstack/react-query";
import { api, queryKeys } from "@/lib/api/client";
import { LayoutDashboard, Briefcase, BarChart3, LogOut, Zap, Plus } from "lucide-react";
import { StatusDot } from "@/components/shared";

const NAV = [
  { href: "/recruiter/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { href: "/recruiter/jobs", icon: Briefcase, label: "Job Postings" },
  { href: "/recruiter/analytics", icon: BarChart3, label: "Analytics" },
];

export default function RecruiterLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { role, userId, userName, isRefreshing } = useAuthStore();
  const { logout: handleLogout } = useLogout();

  useEffect(() => {
    if (!userId || role !== "recruiter") router.push("/login");
  }, [userId, role, router]);

  const { data: healthData } = useQuery({
    queryKey: queryKeys.healthServices(),
    queryFn: () => api.getHealthServices(),
    refetchInterval: 30_000,
  });




  if (!userId || role !== "recruiter" || isRefreshing) return null;

  return (
    <div className="flex min-h-screen bg-charcoal-950">
      <aside className="w-60 flex-shrink-0 flex flex-col bg-charcoal-900 border-r border-white/[0.06] fixed h-full z-20">
        <div className="p-5 border-b border-white/[0.06]">
          <Link href="/recruiter/dashboard" className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-electric-500/15 border border-electric-500/30 flex items-center justify-center">
              <Zap className="w-4 h-4 text-electric-400" />
            </div>
            <span className="font-display text-lg font-bold text-text-primary">
              ATS<span className="text-electric-400">Pro</span>
            </span>
          </Link>
        </div>

        <div className="px-4 py-3 border-b border-white/[0.06]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-volt-400/20 flex items-center justify-center text-volt-400 text-sm font-bold">
              {userName?.[0]?.toUpperCase() ?? "R"}
            </div>
            <div className="min-w-0">
              <div className="text-sm font-medium text-text-primary truncate">{userName}</div>
              <div className="text-xs text-text-muted">Recruiter</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-0.5">
          {NAV.map(({ href, icon: Icon, label }) => {
            const active = pathname === href || pathname.startsWith(href + "/");
            return (
              <Link key={href} href={href} className={active ? "nav-item-active" : "nav-item"}>
                <Icon className="w-4 h-4 flex-shrink-0" />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="p-3 border-t border-white/[0.06] space-y-1">
          <Link href="/recruiter/jobs/new" className="nav-item text-volt-400 hover:bg-volt-400/10 hover:text-volt-400 w-full">
            <Plus className="w-4 h-4" /> Post a Job
          </Link>
          <div className="flex items-center gap-2 px-3 py-2 text-xs text-text-muted">
            <StatusDot status={healthData ? (healthData.data?.all_optional_services_available ? "online" : "offline") : "loading"} />
            <span>AI {healthData?.data?.all_optional_services_available ? "Online" : "Degraded"}</span>
          </div>
          <button onClick={handleLogout} className="nav-item w-full text-red-400 hover:bg-red-500/10 hover:text-red-300">
            <LogOut className="w-4 h-4" /> Sign out
          </button>
        </div>
      </aside>

      <main className="flex-1 ml-60 min-h-screen">
        <div className="page-enter">{children}</div>
      </main>
    </div>
  );
}
