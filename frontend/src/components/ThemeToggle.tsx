/**
 * Theme manager + button.
 *
 * Reads `color_theme` from settings on mount, applies it to <html>, and shows
 * a sun/moon button that flips the value and saves. The change is reflected
 * immediately without round-tripping through useQuery's stale window.
 */
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Moon, Sun } from "lucide-react";
import { api } from "../api";

const THEME_KEY = "portfolioDashboard.theme";

function applyTheme(theme: "dark" | "light"): void {
  const root = document.documentElement;
  if (theme === "dark") root.classList.add("dark");
  else root.classList.remove("dark");
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* private mode or quota — fine to ignore */
  }
}

export default function ThemeToggle() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: 60_000 });

  // Apply theme whenever settings update.
  useEffect(() => {
    if (q.data) applyTheme(q.data.color_theme);
  }, [q.data?.color_theme]);

  // First render before settings load: respect a previously-applied class on
  // <html>, defaulting to dark for backward compatibility.
  useEffect(() => {
    if (!q.data && !document.documentElement.classList.contains("dark")) {
      applyTheme("dark");
    }
  }, []);

  const toggle = useMutation({
    mutationFn: async () => {
      if (!q.data) return;
      const next = q.data.color_theme === "dark" ? "light" : "dark";
      applyTheme(next);                          // optimistic
      return api.saveSettings({ ...q.data, color_theme: next });
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  const current = q.data?.color_theme ?? "dark";
  return (
    <button
      className="btn-ghost p-2"
      onClick={() => toggle.mutate()}
      title={current === "dark" ? "Switch to light mode" : "Switch to dark mode"}
    >
      {current === "dark" ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}
