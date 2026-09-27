"use client";

import { CircleCheck, Info, TriangleAlert, X } from "lucide-react";
import { useEffect, useRef, useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

/**
 * Toasts: short messages after an action ("Name saved", "Key revoked").
 *
 *   toast.success("Name saved.");
 *   toast.error("Could not save. Try again.");
 *   toast("Checklist hidden.", { action: { label: "Undo", onClick: restore } });
 *
 * Use toasts for results of actions. Keep errors about a form INSIDE the form (next to the
 * field), because a toast disappears and is easy to miss.
 */

type Tone = "info" | "success" | "error";

export type ToastOptions = {
  tone?: Tone;
  description?: string;
  /** One button, e.g. Undo. Clicking it also closes the toast. */
  action?: { label: string; onClick: () => void };
  /** Milliseconds on screen. Errors stay longer by default. */
  duration?: number;
};

type ToastItem = Required<Pick<ToastOptions, "tone" | "duration">> &
  Omit<ToastOptions, "tone" | "duration"> & { id: number; message: string };

const MAX_VISIBLE = 3;
let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const EMPTY: ToastItem[] = [];

function show(message: string, options: ToastOptions = {}): number {
  const tone = options.tone ?? "info";
  const item: ToastItem = {
    ...options,
    id: nextId++,
    message,
    tone,
    duration: options.duration ?? (tone === "error" ? 8000 : 5000),
  };
  items = [...items, item].slice(-MAX_VISIBLE);
  emit();
  return item.id;
}

function dismiss(id?: number) {
  items = id === undefined ? [] : items.filter((t) => t.id !== id);
  emit();
}

export const toast = Object.assign(show, {
  success: (message: string, options?: Omit<ToastOptions, "tone">) =>
    show(message, { ...options, tone: "success" }),
  error: (message: string, options?: Omit<ToastOptions, "tone">) =>
    show(message, { ...options, tone: "error" }),
  dismiss,
});

const ICONS = { info: Info, success: CircleCheck, error: TriangleAlert } as const;
const ICON_COLOR = { info: "text-accent", success: "text-success", error: "text-danger" } as const;

/** Renders the toasts. Mounted once in app/layout.tsx. */
export function Toaster() {
  const list = useSyncExternalStore(
    subscribe,
    () => items,
    () => EMPTY,
  );
  return (
    <section
      aria-label="Notifications"
      className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:items-end"
    >
      <ol className="flex w-full max-w-sm flex-col gap-2" aria-live="polite">
        {list.map((item) => (
          <ToastCard key={item.id} item={item} />
        ))}
      </ol>
    </section>
  );
}

function ToastCard({ item }: { item: ToastItem }) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const Icon = ICONS[item.tone];

  const start = () => {
    stop();
    timer.current = setTimeout(() => dismiss(item.id), item.duration);
  };
  const stop = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };

  useEffect(() => {
    // Auto-close timer (an external timer, cleaned up on unmount).
    timer.current = setTimeout(() => dismiss(item.id), item.duration);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [item.id, item.duration]);

  return (
    <li
      role={item.tone === "error" ? "alert" : "status"}
      data-tone={item.tone}
      // Pause while the pointer or keyboard focus is on the toast, so it can be read.
      onMouseEnter={stop}
      onMouseLeave={start}
      onFocus={stop}
      onBlur={start}
      className={cn(
        "pointer-events-auto flex items-start gap-3 rounded-menu border border-line bg-surface p-3 pr-2",
        "animate-in shadow-lg shadow-ink/10 fade-in-0 slide-in-from-bottom-2",
      )}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", ICON_COLOR[item.tone])} aria-hidden="true" />
      <div className="min-w-0 flex-1 space-y-0.5 text-sm">
        <p className="font-medium">{item.message}</p>
        {item.description && <p className="text-ink-muted">{item.description}</p>}
      </div>
      {item.action && (
        <button
          type="button"
          onClick={() => {
            item.action?.onClick();
            dismiss(item.id);
          }}
          className="shrink-0 rounded-control px-2 py-1 text-sm font-medium text-accent hover:bg-accent-soft"
        >
          {item.action.label}
        </button>
      )}
      <button
        type="button"
        onClick={() => dismiss(item.id)}
        aria-label="Close notification"
        className="shrink-0 rounded-control p-1 text-ink-muted hover:bg-surface-sunken hover:text-ink"
      >
        <X className="size-4" aria-hidden="true" />
      </button>
    </li>
  );
}
