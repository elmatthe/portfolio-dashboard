import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, Plus, Trash2 } from "lucide-react";
import clsx from "clsx";
import { api, fmt } from "../api";
import type { Profile } from "../types";
import { useProfile } from "./ProfileContext";
import { useToast } from "./Toast";

const PRESET_COLORS = [
  { name: "Blue",   value: "#3B82F6" },
  { name: "Green",  value: "#10B981" },
  { name: "Purple", value: "#8B5CF6" },
  { name: "Orange", value: "#F59E0B" },
  { name: "Red",    value: "#EF4444" },
  { name: "Teal",   value: "#14B8A6" },
];

interface Props {
  /** Called after a profile is created (so App can route to Upload). */
  onProfileCreated?: () => void;
}

export default function ProfileSwitcher({ onProfileCreated }: Props) {
  const ctx = useProfile();
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const activate = useMutation({
    mutationFn: (id: string) => api.activateProfile(id),
    onSuccess: (profile) => {
      toast.push(`Switched to "${profile.name}"`, "success");
      // Profile change = full data refresh.
      qc.invalidateQueries();
      ctx.refetch();
      setOpen(false);
    },
    onError: (e: Error) => toast.push(e.message || "Switch failed", "error"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteProfile(id),
    onSuccess: () => {
      toast.push("Profile deleted", "success");
      qc.invalidateQueries();
      ctx.refetch();
    },
    onError: (e: Error) => toast.push(e.message || "Delete failed", "error"),
  });

  const active = ctx.active;
  if (!active) {
    return <div className="text-xs text-text-muted">Loading profile…</div>;
  }

  return (
    <div className="relative" ref={wrapRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className={clsx(
          "inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm",
          "bg-white/5 hover:bg-white/10 border border-border transition-colors",
        )}
      >
        <span
          className="inline-block w-2.5 h-2.5 rounded-full"
          style={{ background: active.color }}
        />
        <span className="font-medium max-w-[14rem] truncate">{active.name}</span>
        <ChevronDown size={14} className="text-text-muted" />
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-72 rounded-xl bg-surface border border-border shadow-xl z-40 overflow-hidden">
          <div className="px-3 py-2 text-xs text-text-muted uppercase tracking-wider border-b border-border">
            Profiles
          </div>
          <div className="max-h-72 overflow-y-auto">
            {ctx.profiles.map((p) => (
              <ProfileRow
                key={p.id}
                profile={p}
                isActive={p.id === ctx.activeId}
                onSelect={() => {
                  if (p.id !== ctx.activeId) activate.mutate(p.id);
                  else setOpen(false);
                }}
                onDelete={() => {
                  if (window.confirm(`Delete "${p.name}" and all its data?`)) {
                    remove.mutate(p.id);
                  }
                }}
              />
            ))}
          </div>
          <button
            className="w-full px-3 py-2.5 text-sm flex items-center gap-2 border-t border-border hover:bg-white/5 text-accent"
            onClick={() => {
              setOpen(false);
              setModalOpen(true);
            }}
          >
            <Plus size={14} /> Add new profile
          </button>
        </div>
      )}

      {modalOpen && (
        <AddProfileModal
          onClose={() => setModalOpen(false)}
          onCreated={() => {
            setModalOpen(false);
            qc.invalidateQueries();
            ctx.refetch();
            onProfileCreated?.();
          }}
        />
      )}
    </div>
  );
}

function ProfileRow({
  profile,
  isActive,
  onSelect,
  onDelete,
}: {
  profile: Profile;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  return (
    <div className={clsx("group flex items-center gap-2 px-3 py-2 hover:bg-white/5", isActive && "bg-white/[0.03]")}>
      <button onClick={onSelect} className="flex-1 flex items-center gap-2 text-left text-sm">
        <span className="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: profile.color }} />
        <span className="flex-1 min-w-0">
          <div className="font-medium truncate">{profile.name}</div>
          <div className="text-xs text-text-muted truncate">
            {profile.last_imported_at
              ? `Last import: ${fmt.date(profile.last_imported_at)}`
              : "No data yet"}
          </div>
        </span>
        {isActive && <Check size={14} className="text-accent flex-shrink-0" />}
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        className="opacity-0 group-hover:opacity-100 transition-opacity p-1 text-text-muted hover:text-loss"
        title="Delete profile"
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}

function AddProfileModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [color, setColor] = useState(PRESET_COLORS[0].value);
  const toast = useToast();
  const qc = useQueryClient();

  const create = useMutation({
    mutationFn: () => api.createProfile(name.trim(), color),
    onSuccess: async (profile) => {
      // Auto-activate the newly created profile.
      await api.activateProfile(profile.id);
      toast.push(`Created "${profile.name}"`, "success");
      qc.invalidateQueries();
      onCreated();
    },
    onError: (e: Error) => toast.push(e.message || "Could not create profile", "error"),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="card w-96 max-w-[90vw]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-lg font-semibold mb-4">New profile</div>

        <label className="block text-xs text-text-muted uppercase tracking-wider mb-1.5">Name</label>
        <input
          autoFocus
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. John's Portfolio"
          className="w-full bg-white/5 border border-border rounded-md px-3 py-2 text-sm mb-4 focus:outline-none focus:border-accent"
          onKeyDown={(e) => {
            if (e.key === "Enter" && name.trim() && !create.isPending) create.mutate();
          }}
        />

        <label className="block text-xs text-text-muted uppercase tracking-wider mb-1.5">Color</label>
        <div className="flex gap-2 mb-6">
          {PRESET_COLORS.map((c) => (
            <button
              key={c.value}
              onClick={() => setColor(c.value)}
              title={c.name}
              className={clsx(
                "w-7 h-7 rounded-full border-2 transition-transform",
                color === c.value ? "border-white scale-110" : "border-transparent",
              )}
              style={{ background: c.value }}
            />
          ))}
        </div>

        <div className="flex justify-end gap-2">
          <button className="btn-ghost" onClick={onClose} disabled={create.isPending}>
            Cancel
          </button>
          <button
            className="btn-primary"
            disabled={!name.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? "Creating…" : "Create & switch"}
          </button>
        </div>
      </div>
    </div>
  );
}
