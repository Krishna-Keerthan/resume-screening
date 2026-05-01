"use client";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { setClientToken } from "@/lib/api/client";

// ─── Shape ────────────────────────────────────────────────────────────────────
// accessToken lives in memory ONLY — never persisted to localStorage.
// role / userId / userName are persisted so the UI survives a page refresh
// (the middleware will call /auth/refresh on mount to re-validate).

interface AuthState {
  // Persisted (across page refreshes)
  role:     "candidate" | "recruiter" | null;
  userId:   string | null;
  userName: string | null;

  // Memory-only (cleared on page reload — re-hydrated via /auth/refresh)
  accessToken: string | null;
  isRefreshing: boolean;

  // Actions
  setAuth: (
    role:        "candidate" | "recruiter",
    userId:      string,
    userName:    string,
    accessToken: string
  ) => void;
  setAccessToken: (token: string) => void;
  setIsRefreshing: (v: boolean) => void;
  logout: () => void;
}

// ─── Store ────────────────────────────────────────────────────────────────────
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      role:        null,
      userId:      null,
      userName:    null,
      accessToken: null,   // NOT in partialize — never hits localStorage

      setAuth: (role, userId, userName, accessToken) =>{
        setClientToken(accessToken);
        set({ role, userId, userName, accessToken });
      },
        
    
      setAccessToken: (accessToken) => {
        setClientToken(accessToken);
        set({ accessToken });
      },

      isRefreshing: false,   // initial value
      setIsRefreshing: (isRefreshing) => set({ isRefreshing }),

      logout: () =>{
          setClientToken(null);
          set({ role: null, userId: null, userName: null, accessToken: null });
      }
        
    }),
    {
      name: process.env.NEXT_PUBLIC_AUTH_STORAGE_KEY ?? "ats-auth-v1",
      // Only persist identity — access token lives in memory only
      partialize: (state) => ({
        role:     state.role,
        userId:   state.userId,
        userName: state.userName,
      }),
    }
  )
);
