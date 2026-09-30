"use client";

import { CreditCard } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { useApiData } from "@/hooks/use-api-data";
import { useDataTable, type Column } from "@/hooks/use-data-table";
import { api, unwrap, type AdminSubscription } from "@/lib/api";
import { formatDate } from "@/lib/format";

const TONE: Record<string, "success" | "warning" | "danger" | "neutral" | "accent"> = {
  active: "success",
  trialing: "accent",
  past_due: "warning",
  unpaid: "danger",
  canceled: "neutral",
};

const columns: Column<AdminSubscription>[] = [
  {
    id: "workspace",
    header: "Workspace",
    hideLabelOnPhone: true,
    sortValue: (s) => s.organization_name,
    cell: (s) => (
      <div className="min-w-0">
        <p className="truncate font-medium">{s.organization_name}</p>
        <p className="truncate font-mono text-xs text-ink-muted">
          {s.stripe_customer_id ?? "no Stripe customer (set by hand)"}
        </p>
      </div>
    ),
  },
  {
    id: "plan",
    header: "Plan",
    className: "sm:w-32",
    sortValue: (s) => s.plan_id ?? "",
    cell: (s) => `${s.plan_id ?? "none"}${s.interval ? ` · ${s.interval}ly` : ""}`,
  },
  {
    id: "status",
    header: "Status",
    className: "sm:w-36",
    sortValue: (s) => s.status ?? "",
    cell: (s) => (
      <span className="flex flex-wrap gap-1">
        <Badge tone={TONE[s.status ?? ""] ?? "neutral"}>{s.status ?? "no subscription"}</Badge>
        {s.cancel_at_period_end && <Badge tone="warning">Ends</Badge>}
      </span>
    ),
  },
  {
    id: "period",
    header: "Renews / ends",
    className: "sm:w-36 text-ink-muted",
    sortValue: (s) => s.current_period_end,
    cell: (s) => (s.current_period_end ? formatDate(s.current_period_end) : "-"),
  },
  {
    id: "updated",
    header: "Updated",
    className: "sm:w-32 text-ink-muted",
    sortValue: (s) => s.updated_at,
    cell: (s) => <span className="tabular">{formatDate(s.updated_at)}</span>,
  },
];

/** Admin → Subscriptions: our copy of Stripe (the webhooks keep it fresh). */
export function AdminSubscriptionsView() {
  const subs = useApiData(async () => (await unwrap(api.GET("/api/admin/subscriptions"))).items);
  const table = useDataTable({
    rows: subs.data,
    columns,
    searchText: (s) => `${s.organization_name} ${s.stripe_customer_id ?? ""} ${s.plan_id ?? ""}`,
    pageSize: 25,
  });
  if (subs.data === null && subs.error)
    return <Alert tone="error">Could not load: {subs.error}</Alert>;
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-muted">
        Stripe is the source of truth. Refunds, invoices and payment details: open the customer in
        the Stripe dashboard.
      </p>
      <DataTable
        table={table}
        label="Subscriptions"
        searchLabel="Search workspace or customer id"
        rowKey={(s) => s.organization_id}
        empty={
          <EmptyState
            icon={CreditCard}
            title="No subscriptions yet"
            description="A row appears when a workspace starts its first checkout."
          />
        }
      />
    </div>
  );
}
