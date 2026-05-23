/**
 * Tiny portal+overlay primitive shared by every modal in the app.
 *
 * Why this exists: every modal previously rendered its `<div className="fixed
 * inset-0 ...">` as a child of its trigger button (in the banner / dropdown).
 * Any ancestor with `transform` / `filter` / `will-change` becomes the
 * containing block for `position: fixed` descendants (CSS spec, not a bug),
 * so the modal collapses into that ancestor's bounds instead of overlaying
 * the viewport. Portal-mounting to <body> guarantees the modal always
 * positions relative to the viewport, regardless of where the trigger lives.
 *
 * Also centralises the Escape-to-close + backdrop-click behaviour so we don't
 * keep re-implementing it per modal.
 */
import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

interface Props {
  onClose: () => void;
  children: ReactNode;
  /** Tailwind classes for the backdrop. Default = dark translucent. */
  backdropClassName?: string;
  /** Optional aria-labelledby id pointing at the modal title. */
  labelledBy?: string;
}

export function ModalPortal({
  onClose,
  children,
  backdropClassName = "fixed inset-0 z-50 bg-black/60 overflow-y-auto",
  labelledBy,
}: Props) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelledBy}
      className={backdropClassName}
      onClick={onClose}
    >
      {children}
    </div>,
    document.body,
  );
}
