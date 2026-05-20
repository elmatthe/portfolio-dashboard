/**
 * Full-page settings overlay covering: Profile, Tax, TFSA, Display, Data.
 * Opened from the gear icon in SyncStatus, closed with the X (top right) or Esc.
 *
 * Edits are local until the user clicks "Save changes" — keeps roundtrips out
 * of the way for users adjusting multiple fields at once.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, X, Trash2, Download } from "lucide-react";
import clsx from "clsx";
import { api } from "../api";
import type { AppSettings } from "../types";
import { useProfile } from "./ProfileContext";
import { useToast } from "./Toast";
import { PERIODS } from "./PeriodContext";

const PRESET_COLORS = [
  { name: "Blue",   value: "#3B82F6" },
  { name: "Green",  value: "#10B981" },
  { name: "Purple", value: "#8B5CF6" },
  { name: "Orange", value: "#F59E0B" },
  { name: "Red",    value: "#EF4444" },
  { name: "Teal",   value: "#14B8A6" },
];

const PROVINCES = [
  "AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT",
];

const CURRENCY_VIEWS: { value: AppSettings["default_currency_view"]; label: string }[] = [
  { value: "combined_cad", label: "Combined in CAD" },
  { value: "combined_usd", label: "Combined in USD" },
  { value: "cad_only", label: "CAD only" },
  { value: "usd_only", label: "USD only" },
];

const REFRESH_INTERVALS = [15, 30, 60];

interface Props {
  onClose: () => void;
}

export default function SettingsPage({ onClose }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const profile = useProfile();

  const q = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [profileName, setProfileName] = useState("");
  const [profileColor, setProfileColor] = useState("#3B82F6");

  // Initialise the local draft once the settings load.
  useEffect(() => {
    if (q.data && draft === null) {
      setDraft(q.data);
    }
  }, [q.data, draft]);
  useEffect(() => {
    if (profile.active) {
      setProfileName(profile.active.name);
      setProfileColor(profile.active.color);
    }
  }, [profile.active]);

  // Close on Esc.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const save = useMutation({
    mutationFn: (s: AppSettings) => api.saveSettings(s),
    onSuccess: () => {
      toast.push("Settings saved", "success");
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["portfolio"] });
    },
    onError: (e: Error) => toast.push(e.message || "Save failed", "error"),
  });

  const renameProfile = useMutation({
    mutationFn: () =>
      api.renameProfile(profile.activeId!, profileName.trim(), profileColor),
    onSuccess: () => {
      toast.push("Profile updated", "success");
      qc.invalidateQueries();
      profile.refetch();
    },
    onError: (e: Error) => toast.push(e.message || "Could not update profile", "error"),
  });

  const removeProfile = useMutation({
    mutationFn: (id: string) => api.deleteProfile(id),
    onSuccess: () => {
      toast.push("Profile deleted", "success");
      qc.invalidateQueries();
      profile.refetch();
      onClose();
    },
    onError: (e: Error) => toast.push(e.message || "Could not delete", "error"),
  });

  const clearData = useMutation({
    mutationFn: api.clearData,
    onSuccess: () => {
      toast.push("Profile data cleared", "success");
      qc.invalidateQueries();
    },
    onError: (e: Error) => toast.push(e.message || "Could not clear data", "error"),
  });

  const isDirty = useMemo(() => {
    if (!q.data || !draft) return false;
    return JSON.stringify(q.data) !== JSON.stringify(draft);
  }, [q.data, draft]);

  if (q.isLoading || !draft) {
    return (
      <Overlay onClose={onClose}>
        <div className="text-text-muted">Loading settings…</div>
      </Overlay>
    );
  }

  const set = <K extends keyof AppSettings>(k: K, v: AppSettings[K]) =>
    setDraft({ ...draft, [k]: v });

  return (
    <Overlay onClose={onClose}>
      <div className="max-w-3xl mx-auto py-8 px-6 space-y-8">
        <div className="flex items-center justify-between sticky top-0 bg-bg z-10 py-2">
          <h1 className="text-2xl font-bold">Settings</h1>
          <div className="flex items-center gap-2">
            {isDirty && (
              <button
                className="btn-primary"
                onClick={() => save.mutate(draft)}
                disabled={save.isPending}
              >
                <Save size={14} /> {save.isPending ? "Saving…" : "Save changes"}
              </button>
            )}
            <button className="btn-ghost" onClick={onClose} title="Close (Esc)">
              <X size={16} />
            </button>
          </div>
        </div>

        {/* ---------- Profile ---------- */}
        <Section title="Profile">
          <Field label="Profile name">
            <input
              type="text"
              value={profileName}
              onChange={(e) => setProfileName(e.target.value)}
              className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm w-full"
            />
          </Field>
          <Field label="Accent color">
            <div className="flex gap-2">
              {PRESET_COLORS.map((c) => (
                <button
                  key={c.value}
                  onClick={() => setProfileColor(c.value)}
                  title={c.name}
                  className={clsx(
                    "w-7 h-7 rounded-full border-2 transition-transform",
                    profileColor === c.value ? "border-white scale-110" : "border-transparent",
                  )}
                  style={{ background: c.value }}
                />
              ))}
            </div>
          </Field>
          <div className="flex gap-2">
            <button
              className="btn-primary"
              onClick={() => renameProfile.mutate()}
              disabled={
                renameProfile.isPending ||
                !profileName.trim() ||
                (profile.active?.name === profileName.trim() &&
                  profile.active?.color === profileColor)
              }
            >
              Update profile
            </button>
            <button
              className="btn-ghost text-loss border border-loss/30 hover:bg-loss/10"
              onClick={() => {
                if (
                  window.confirm(
                    `Delete profile "${profile.active?.name}"? Its database will be removed permanently.`,
                  )
                )
                  removeProfile.mutate(profile.activeId!);
              }}
              disabled={removeProfile.isPending}
            >
              <Trash2 size={14} /> Delete profile
            </button>
          </div>
        </Section>

        {/* ---------- Tax ---------- */}
        <Section title="Tax settings" hint="Used by the What-If Simulator and future tax reports.">
          <Field label={`Marginal tax rate (${(draft.marginal_tax_rate * 100).toFixed(0)}%)`}>
            <input
              type="range"
              min={0}
              max={0.55}
              step={0.01}
              value={draft.marginal_tax_rate}
              onChange={(e) => set("marginal_tax_rate", parseFloat(e.target.value))}
              className="w-full"
            />
          </Field>
          <Field label="Province">
            <select
              value={draft.tax_province}
              onChange={(e) => set("tax_province", e.target.value)}
              className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm"
            >
              {PROVINCES.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </Field>
        </Section>

        {/* ---------- TFSA ---------- */}
        <Section title="TFSA settings" hint="Required to calculate your contribution room.">
          <Field label="Birth year">
            <input
              type="number"
              min={1940}
              max={2010}
              value={draft.tfsa_birth_year ?? ""}
              onChange={(e) =>
                set("tfsa_birth_year", e.target.value ? parseInt(e.target.value, 10) : null)
              }
              placeholder="e.g. 1995"
              className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm w-40"
            />
          </Field>
          <Field label="Year you became a Canadian resident">
            <input
              type="number"
              min={2009}
              max={new Date().getFullYear()}
              value={draft.tfsa_resident_since ?? ""}
              onChange={(e) =>
                set("tfsa_resident_since", e.target.value ? parseInt(e.target.value, 10) : null)
              }
              placeholder="e.g. 2018"
              className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm w-40"
            />
          </Field>
        </Section>

        {/* ---------- Display ---------- */}
        <Section title="Display">
          <Field label="Default time period">
            <select
              value={draft.default_period}
              onChange={(e) => set("default_period", e.target.value as AppSettings["default_period"])}
              className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm"
            >
              {PERIODS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Default currency view">
            <select
              value={draft.default_currency_view}
              onChange={(e) =>
                set("default_currency_view", e.target.value as AppSettings["default_currency_view"])
              }
              className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm"
            >
              {CURRENCY_VIEWS.map((v) => (
                <option key={v.value} value={v.value}>{v.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Color theme">
            <div className="flex gap-2">
              {(["dark", "light"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => set("color_theme", t)}
                  className={clsx(
                    "btn",
                    draft.color_theme === t ? "bg-accent text-white" : "bg-white/5 text-text-muted",
                  )}
                >
                  {t === "dark" ? "Dark" : "Light"}
                </button>
              ))}
            </div>
          </Field>
        </Section>

        {/* ---------- Data ---------- */}
        <Section title="Data">
          <Field label="Price refresh interval">
            <select
              value={draft.price_refresh_interval_min}
              onChange={(e) => set("price_refresh_interval_min", parseInt(e.target.value, 10))}
              className="bg-white/5 border border-border rounded-md px-3 py-2 text-sm"
            >
              {REFRESH_INTERVALS.map((m) => (
                <option key={m} value={m}>{m} minutes</option>
              ))}
            </select>
          </Field>
          <div className="flex gap-2 mt-2">
            <a className="btn-ghost" href={api.exportJsonUrl()}>
              <Download size={14} /> Export all data (JSON)
            </a>
            <button
              className="btn-ghost text-loss border border-loss/30 hover:bg-loss/10"
              onClick={() => {
                if (
                  window.confirm(
                    "Clear all transactions and holdings for this profile? Settings will be preserved.",
                  )
                )
                  clearData.mutate();
              }}
              disabled={clearData.isPending}
            >
              <Trash2 size={14} /> Clear all data
            </button>
          </div>
        </Section>
      </div>
    </Overlay>
  );
}

function Overlay({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 bg-bg overflow-y-auto" onClick={onClose}>
      <div className="min-h-full" onClick={(e) => e.stopPropagation()}>{children}</div>
    </div>
  );
}

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="card space-y-4">
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        {hint && <p className="text-xs text-text-muted mt-1">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="label-muted">{label}</div>
      {children}
    </div>
  );
}
