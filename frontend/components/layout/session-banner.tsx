"use client";

import { Eye, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/session-provider";
import { toast } from "@/components/ui/toast";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatTime } from "@/lib/format";

/**
 * Two special sessions get a line on every page:
 * - an app admin viewing the app as a customer (support), with "Stop viewing";
 * - the shared demo user, with a way to create a real account.
 */
export function SessionBanner() {
  const { user, impersonator } = useSession();
  if (impersonator) return <ImpersonationNote />;
  if (user.is_demo) return <DemoNote />;
  return null;
}

function ImpersonationNote() {
  const { user, impersonator } = useSession();
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function stop() {
    setBusy(true);
    try {
      const result = await unwrap(api.POST("/api/admin/impersonation/stop"));
      router.replace(result.restored_admin_session ? "/admin/users" : "/login");
      router.refresh();
    } catch (err) {
      toast.error(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <div
      role="status"
      className="border-b border-warning/30 bg-warning/10"
      data-testid="impersonating"
    >
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm text-warning sm:px-8">
        <Eye className="size-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 flex-1">
          You are viewing the app as <strong>{user.name}</strong> ({user.email}) for support.
          Everything you do is recorded in their audit log. Ends at{" "}
          {formatTime(impersonator!.ends_at)}.
        </span>
        <button
          type="button"
          disabled={busy}
          onClick={() => void stop()}
          className="font-medium underline underline-offset-2 disabled:opacity-60"
        >
          {busy ? "Stopping…" : "Stop viewing"}
        </button>
      </p>
    </div>
  );
}

function DemoNote() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function signUp() {
    setBusy(true);
    try {
      await unwrap(api.POST("/api/auth/logout"));
    } catch {
      // Signed out anyway once the session is gone; go on to sign-up.
    }
    router.replace("/signup");
    router.refresh();
  }

  return (
    <div
      role="status"
      className="border-b border-accent/20 bg-accent-soft"
      data-testid="demo-banner"
    >
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm text-accent sm:px-8">
        <Sparkles className="size-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 flex-1">
          This is a shared demo with sample data: look around freely. Changes are switched off, and
          it resets every night.
        </span>
        <button
          type="button"
          disabled={busy}
          onClick={() => void signUp()}
          className="font-medium underline underline-offset-2 disabled:opacity-60"
        >
          Create your free account
        </button>
      </p>
    </div>
  );
}
