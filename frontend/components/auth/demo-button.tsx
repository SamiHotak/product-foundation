"use client";

import { Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { api, errorMessage, unwrap } from "@/lib/api";

/**
 * "Try the demo": signs in to a shared workspace with sample data (read-mostly, reset
 * every night). Only shown when the backend has DEMO_ENABLED=true.
 */
export function DemoButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      await unwrap(api.POST("/api/auth/demo"));
      router.replace("/dashboard");
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 space-y-3 border-t border-line pt-6">
      {error && <Alert tone="error">{error}</Alert>}
      <button
        type="button"
        onClick={() => void start()}
        disabled={busy}
        className="flex h-10 w-full items-center justify-center gap-2 rounded-control border border-accent/30 bg-accent-soft text-sm font-medium text-accent hover:bg-accent-soft/70 disabled:opacity-60"
      >
        <Sparkles className="size-4" aria-hidden="true" />
        {busy ? "Opening the demo…" : "Try the demo, no sign-up"}
      </button>
      <p className="text-center text-xs text-ink-muted">
        A shared workspace with sample data. It resets every night.
      </p>
    </div>
  );
}
