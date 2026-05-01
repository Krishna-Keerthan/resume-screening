import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { AuthProvider } from "@/components/AuthProvider";
import { Toaster } from "sonner";

export const metadata: Metadata = {
  title: "ATS Platform — AI Resume Intelligence",
  description: "AI-powered applicant tracking and resume intelligence platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <AuthProvider>
            {children}
          </AuthProvider>
        </Providers>
        <Toaster
          theme="dark"
          position="bottom-right"
          toastOptions={{
            style: {
              background: "#1A1E29",
              border: "1px solid rgba(255,255,255,0.07)",
              color: "#F1F3F9",
              fontFamily: "'DM Sans', sans-serif",
            },
          }}
        />
      </body>
    </html>
  );
}
