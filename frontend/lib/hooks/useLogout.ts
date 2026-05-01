"use client";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/store/authStore";
import { api, setClientToken, ApiError } from "@/lib/api/client";
import { toast } from "sonner";

// ─── useLogout ────────────────────────────────────────────────────────────────
// Provides logout() and logoutAll() functions.
// Clears local state + calls backend to revoke the refresh token.
// ─────────────────────────────────────────────────────────────────────────────

export function useLogout() {
  const router = useRouter();
  const { logout: clearStore } = useAuthStore();

  const _cleanUp = () => {
    setClientToken(null);  // Clear Axios Bearer header memory
    clearStore();          // Clear Zustand (localStorage + in-memory)
    router.push("/login");
  };

  // Revoke current device only
  const logout = async () => {
    try {
      await api.authLogout();
    } catch (err) {
      // Even if the backend call fails (e.g. already expired), clear locally
      const code = err instanceof ApiError ? err.code : "";
      if (code !== "MISSING_TOKEN" && code !== "TOKEN_EXPIRED") {
        toast.error("Logout error — cleared locally.");
      }
    } finally {
      _cleanUp();
    }
  };

  // Revoke all devices ("sign out everywhere")
  const logoutAll = async () => {
    try {
      const res = await api.authLogoutAll();
      const count = res.data?.sessions_revoked ?? 0;
      toast.success(`Signed out from ${count} device${count !== 1 ? "s" : ""}.`);
    } catch {
      toast.error("Could not revoke all sessions — cleared locally.");
    } finally {
      _cleanUp();
    }
  };

  return { logout, logoutAll };
}
