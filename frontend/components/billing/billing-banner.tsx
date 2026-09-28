"use client";

import { CreditCard } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSession } from "@/components/session-provider";
import { useApiData } from "@/hooks/use-api-data";
import { api, unwrap } from "@/lib/api";

/**
 * Shown to the owner on every page while a payment has failed (Stripe is retrying), so
 * the plan does not end by surprise. Everyone else never sees billing details here.
 */
export function BillingBanner() {
  const { activeOrganization } = useSession();
  // A new workspace = a fresh load (the app stays mounted when you switch).
  return <PastDueNote key={activeOrganization.id} />;
}

function PastDueNote() {
  const { can, activeOrganization } = useSession();
  const owner = can("billing:manage");
  const pathname = usePathname();
  const { data } = useApiData(async () =>
    owner ? await unwrap(api.GET("/api/billing/current")) : null,
  );
  if (!data || data.status !== "past_due" || pathname === "/settings/billing") return null;
  return (
    <div role="status" className="border-b border-warning/30 bg-warning/5">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm text-warning sm:px-8">
        <CreditCard className="size-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 flex-1">
          The last payment for “{activeOrganization.name}” failed. Update the payment method to keep
          the {data.plan_name} plan.
        </span>
        <Link href="/settings/billing" className="font-medium underline underline-offset-2">
          Update payment method
        </Link>
      </p>
    </div>
  );
}
