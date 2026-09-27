"use client";

import { CreditCard, Receipt } from "lucide-react";

import { useSession } from "@/components/session-provider";
import { NoAccess, Section } from "@/components/settings/section";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";

/**
 * Settings → Billing. A placeholder until Stripe is connected (phase 4A):
 * it shows the honest current state (free, nothing to pay) and where things will be.
 */
export function BillingSettings() {
  const { can, activeOrganization } = useSession();
  if (!can("billing:manage")) {
    return <NoAccess>Only the owner of this workspace manages billing.</NoAccess>;
  }
  return (
    <div className="space-y-12">
      <Section title="Plan" description={`The plan of “${activeOrganization.name}”.`}>
        <div className="flex flex-wrap items-start gap-4 rounded-menu border border-line p-5">
          <div className="min-w-0 flex-1 space-y-1">
            <p className="flex items-center gap-2 font-semibold">
              Free <Badge tone="accent">Current plan</Badge>
            </p>
            <p className="max-w-prose text-sm text-ink-muted">
              Everything is free while paid plans are not available yet. You will be able to choose
              a plan here, and nothing is charged without your OK.
            </p>
          </div>
        </div>
      </Section>
      <Section title="Payment method">
        <EmptyState
          icon={CreditCard}
          title="No payment method"
          description="Not needed on the free plan. Card details will be handled by Stripe and never stored by us."
        />
      </Section>
      <Section title="Invoices">
        <EmptyState
          icon={Receipt}
          title="No invoices yet"
          description="Invoices appear here as PDFs once you are on a paid plan."
        />
      </Section>
    </div>
  );
}
