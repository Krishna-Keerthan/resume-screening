import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ["'Syne'", "sans-serif"],
        body: ["'DM Sans'", "sans-serif"],
        mono: ["'JetBrains Mono'", "monospace"],
      },
      colors: {
        charcoal: {
          950: "#0D0F14",
          900: "#13161D",
          800: "#1A1E29",
          700: "#232839",
          600: "#2E3448",
          500: "#3B4058",
        },
        electric: {
          400: "#60EFFF",
          500: "#00D4FF",
          600: "#00B8E6",
        },
        volt: {
          400: "#AAFF00",
          500: "#88FF00",
        },
        score: {
          excellent: "#10B981",
          good: "#3B82F6",
          fair: "#F59E0B",
          weak: "#EF4444",
        },
      },
      backgroundImage: {
        "grid-pattern":
          "linear-gradient(rgba(0,212,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(0,212,255,0.03) 1px, transparent 1px)",
        "glow-radial":
          "radial-gradient(ellipse at top, rgba(0,212,255,0.12) 0%, transparent 60%)",
      },
      backgroundSize: {
        grid: "40px 40px",
      },
      animation: {
        "fade-in": "fadeIn 0.4s ease forwards",
        "slide-up": "slideUp 0.4s ease forwards",
        "slide-in-right": "slideInRight 0.35s ease forwards",
        "pulse-glow": "pulseGlow 2s ease-in-out infinite",
        "count-up": "countUp 1s ease forwards",
      },
      keyframes: {
        fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
        slideUp: {
          from: { opacity: "0", transform: "translateY(16px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          from: { opacity: "0", transform: "translateX(24px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        pulseGlow: {
          "0%, 100%": { boxShadow: "0 0 20px rgba(0,212,255,0.2)" },
          "50%": { boxShadow: "0 0 40px rgba(0,212,255,0.5)" },
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
};

export default config;
