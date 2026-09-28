"use client";

import Link from "next/link";

import { useSession } from "@/components/session-provider";
import { Alert } from "@/components/ui/alert";
import { isLimitReached } from "@/lib/api";

/**
 * An error from the API, shown above a form or next to a button.
 * "Limit reached" (HTTP 402) gets the way out: "See plans" for the owner, and
 * "ask the owner" for everyone else.
 *
 *   {form.formError && <ApiErrorAlert message={form.formError} cause={form.formErrorCause} />}
 */
export function ApiErrorAlert({
  message,
  cause,
  className,
}: {
  message: string;
  cause?: unknown;
  className?: string;
}) {
  const { can } = useSession();
  if (!isLimitReached(cause)) {
    return (
      <Alert tone="error" className={className}>
        {message}
      </Alert>
    );
  }
  return (
    <Alert tone="error" className={className}>
      <p>{message}</p>
      {can("billing:manage") ? (
        <p>
          <Link href="/settings/billing" className="font-medium underline underline-offset-2">
            See plans
          </Link>
        </p>
      ) : (
        <p>Ask the owner of this workspace to upgrade the plan.</p>
      )}
    </Alert>
  );
}
