/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Theme palette is fed by CSS variables so Light/Dark swap is a single
        // class toggle on <html>.  The rgb triplet form lets Tailwind alpha
        // syntax (`bg-surface/40`) keep working.
        bg: "rgb(var(--bg-rgb) / <alpha-value>)",
        surface: "rgb(var(--surface-rgb) / <alpha-value>)",
        border: "rgb(var(--border-rgb) / <alpha-value>)",
        accent: "rgb(var(--accent-rgb) / <alpha-value>)",
        gain: "#10B981",
        loss: "#EF4444",
        text: {
          primary: "rgb(var(--text-primary-rgb) / <alpha-value>)",
          muted: "rgb(var(--text-muted-rgb) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["Geist Mono", "JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderColor: {
        DEFAULT: "rgba(255,255,255,0.07)",
      },
    },
  },
  plugins: [],
};
