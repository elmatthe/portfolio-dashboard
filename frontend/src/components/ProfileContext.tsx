import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { Profile, ProfilesListResponse } from "../types";

/** Convert "#3B82F6" → "59 130 246" (the form Tailwind's rgb(<var> / <alpha>) wants). */
function hexToRgbTriplet(hex: string): string {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!m) return "59 130 246"; // fall back to default blue
  return `${parseInt(m[1], 16)} ${parseInt(m[2], 16)} ${parseInt(m[3], 16)}`;
}

export const DEFAULT_PROFILE_COLOR = "#3B82F6";

interface ProfileContextValue {
  profiles: Profile[];
  active: Profile | null;
  activeId: string | null;
  accentColor: string;
  isLoading: boolean;
  refetch: () => void;
}

const ProfileContext = createContext<ProfileContextValue>({
  profiles: [],
  active: null,
  activeId: null,
  accentColor: DEFAULT_PROFILE_COLOR,
  isLoading: true,
  refetch: () => {},
});

export function ProfileProvider({ children }: { children: ReactNode }) {
  const q = useQuery<ProfilesListResponse>({
    queryKey: ["profiles"],
    queryFn: api.profiles,
    staleTime: 0,
  });

  const value = useMemo<ProfileContextValue>(() => {
    const profiles = q.data?.profiles ?? [];
    const activeId = q.data?.active_profile_id ?? null;
    const active = activeId ? profiles.find((p) => p.id === activeId) ?? null : null;
    return {
      profiles,
      active,
      activeId,
      accentColor: active?.color || DEFAULT_PROFILE_COLOR,
      isLoading: q.isLoading,
      refetch: () => q.refetch(),
    };
  }, [q.data, q.isLoading, q.refetch]);

  // Push the active accent into the CSS custom property so every Tailwind
  // `bg-accent`, `text-accent`, `border-accent`, `ring-accent` reference picks
  // it up automatically.
  useEffect(() => {
    document.documentElement.style.setProperty(
      "--accent-rgb",
      hexToRgbTriplet(value.accentColor),
    );
  }, [value.accentColor]);

  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>;
}

export function useProfile(): ProfileContextValue {
  return useContext(ProfileContext);
}
