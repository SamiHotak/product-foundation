"use client";

import { TriangleAlert } from "lucide-react";
import Link from "next/link";

import { useSession } from "@/components/session-provider";
import { formatDate } from "@/lib/format";

/**
 * Shown on every page while the account or the active workspace is scheduled for
 * deletion, so nobody is surprised. Cancelling happens in Settings → Privacy.
 */
export function DeletionBanner() {
  const { user, activeOrganization, can } = useSession();
  const notes: { key: string; text: string; action: string | null }[] = [];
  if (user.deletion_scheduled_at) {
    notes.push({
      key: "account",
      text: `Your account will be deleted on ${formatDate(user.deletion_scheduled_at)}.`,
      action: "Keep my account",
    });
  }
  if (activeOrganization.deletion_scheduled_at) {
    notes.push({
      key: "workspace",
      text: `The workspace “${activeOrganization.name}” will be deleted on ${formatDate(
        activeOrganization.deletion_scheduled_at,
      )}.`,
      action: can("org:delete") ? "Keep the workspace" : null,
    });
  }
  if (notes.length === 0) return null;
  return (
    <div role="status" className="border-b border-danger/30 bg-danger/5">
      {notes.map((note) => (
        <p
          key={note.key}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm text-danger sm:px-8"
        >
          <TriangleAlert className="size-4 shrink-0" aria-hidden="true" />
          <span className="min-w-0 flex-1">{note.text}</span>
          {note.action && (
            <Link href="/settings/privacy" className="font-medium underline underline-offset-2">
              {note.action}
            </Link>
          )}
        </p>
      ))}
    </div>
  );
}
