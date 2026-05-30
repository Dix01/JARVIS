import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        jarvis: {
          cyan:   "#7dd3fc",   // softer, premium cyan
          aqua:   "#a5f3fc",
          ice:    "#e0f2fe",
          deep:   "#0a1424",
          ink:    "#03070f",
          abyss:  "#01030a",
          panel:  "rgba(12, 22, 38, 0.42)",
          glass:  "rgba(255, 255, 255, 0.04)",
          glow:   "#bae6fd",
          violet: "#a78bfa",
          gold:   "#fbbf24",
          danger: "#fb7185",
          warn:   "#fbbf24",
          ok:     "#4ade80",
        },
      },
      fontFamily: {
        mono: ["Geist Mono", "JetBrains Mono", "Fira Code", "Consolas", "monospace"],
        display: ["Inter", "Rajdhani", "system-ui", "sans-serif"],
        sans: ["Inter", "Rajdhani", "system-ui", "sans-serif"],
        techno: ["Orbitron", "Inter", "sans-serif"],
      },
      backdropBlur: {
        xs: "2px",
        "3xl": "48px",
        "4xl": "72px",
      },
      keyframes: {
        scan: { "0%": { transform: "translateY(-10vh)", opacity: "0" }, "10%": { opacity: "0.6" }, "90%": { opacity: "0.6" }, "100%": { transform: "translateY(110vh)", opacity: "0" } },
        flicker: { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0.78" } },
        spin_slow: { from: { transform: "rotate(0deg)" }, to: { transform: "rotate(360deg)" } },
        spin_rev: { from: { transform: "rotate(360deg)" }, to: { transform: "rotate(0deg)" } },
        pulse_glow: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(125,211,252,0.0), 0 0 18px rgba(125,211,252,0.25)" },
          "50%":      { boxShadow: "0 0 0 4px rgba(125,211,252,0.08), 0 0 32px rgba(125,211,252,0.55)" },
        },
        boot_in: { from: { opacity: "0", transform: "translateY(8px) scale(0.985)" }, to: { opacity: "1", transform: "translateY(0) scale(1)" } },
        aurora_drift: {
          "0%, 100%": { transform: "translate3d(0,0,0) scale(1)" },
          "33%":      { transform: "translate3d(4%,-3%,0) scale(1.08)" },
          "66%":      { transform: "translate3d(-3%,2%,0) scale(0.96)" },
        },
        shimmer: {
          "0%":   { transform: "translateX(-120%)" },
          "100%": { transform: "translateX(220%)" },
        },
        float_y: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%":      { transform: "translateY(-6px)" },
        },
      },
      animation: {
        scan: "scan 9s cubic-bezier(0.4,0,0.2,1) infinite",
        flicker: "flicker 4s ease-in-out infinite",
        spin_slow: "spin_slow 24s linear infinite",
        spin_rev: "spin_rev 36s linear infinite",
        pulse_glow: "pulse_glow 3.5s ease-in-out infinite",
        boot_in: "boot_in 0.55s cubic-bezier(0.16,1,0.3,1) both",
        aurora: "aurora_drift 22s ease-in-out infinite",
        shimmer: "shimmer 2.4s linear infinite",
        float_y: "float_y 6s ease-in-out infinite",
      },
      backgroundImage: {
        grid: "linear-gradient(rgba(125,211,252,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(125,211,252,0.04) 1px, transparent 1px)",
      },
      backgroundSize: {
        grid: "44px 44px",
      },
    },
  },
  plugins: [],
} satisfies Config;
