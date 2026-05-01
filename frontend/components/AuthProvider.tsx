"use client";

import { useEffect, useState , useRef } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuthStore } from "@/lib/store/authStore";
import { api, setClientToken, ApiError } from "@/lib/api/client";
import { Candidate, Recruiter } from "@/lib/types";

const PUBLIC_PATHS = ["/login"];


// ─────────────────────────────────────────────
// Hydration Hook
// ─────────────────────────────────────────────
function useAuthHydrated() {
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const unsub = useAuthStore.persist.onFinishHydration(() => {
      setHydrated(true);
    });

    setHydrated(useAuthStore.persist.hasHydrated());

    return unsub;
  }, []);

  return hydrated;
}


// ─────────────────────────────────────────────
// Auth Provider
// ─────────────────────────────────────────────
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router   = useRouter();
  const pathname = usePathname();
  const hydrated = useAuthHydrated();

  const { setAuth, logout, setIsRefreshing } = useAuthStore();
  
  // This ref survives re-renders but resets on true unmount/remount.
  // In React Strict Mode the double-invoke unmounts between the two runs,
  // so the cleanup cancels the first in-flight call before the second fires.
  const didRunRef = useRef(false);

  useEffect(() => {
    if (!hydrated) return;
    if (didRunRef.current) return;   // ← guard: skip if already ran
    didRunRef.current = true;

    setIsRefreshing(true);

    (async () => {
      try {
        const res = await api.authRefresh();
        const { access_token, role, user } = res.data;
        setClientToken(access_token);
        setAuth(
          role,
          (user as Candidate | Recruiter).id,
          (user as Candidate | Recruiter).full_name,
          access_token
        );
      } catch (err) {
        const code = err instanceof ApiError ? err.code : "";
        const AUTH_EXPIRY_CODES = new Set([
          "REFRESH_EXPIRED", "MISSING_TOKEN", "TOKEN_REUSED",
          "INVALID_TOKEN",   "TOKEN_INVALID",
        ]);
        if (AUTH_EXPIRY_CODES.has(code)) {
          logout();
          setClientToken(null);
          if (!PUBLIC_PATHS.includes(pathname)) {
            router.push("/login");
          }
        } else {
          console.error("[AuthProvider] Refresh failed:", err);
          if (!PUBLIC_PATHS.includes(pathname)) {
            router.push("/login?reason=session_check_failed");
          }
        }
      } finally {
        setIsRefreshing(false);
      }
    })();

    // Cleanup: if the component unmounts mid-flight (Strict Mode),
    // reset the ref so the remount gets a fresh run
    return () => {
      didRunRef.current = false;
    };
  }, [hydrated]);

  const isRefreshing = useAuthStore((s) => s.isRefreshing);
  if (!hydrated || isRefreshing) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span>Loading...</span>
      </div>
    );
  }

  return <>{children}</>;
}