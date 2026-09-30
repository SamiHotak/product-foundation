"use client";

import { Building2 } from "lucide-react";

import { formatUsd } from "@/components/admin/admin-overview";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { useApiData } from "@/hooks/use-api-data";
import { useDataTable, type Column, type Filter } from "@/hooks/use-data-table";
import { api, unwrap, type AdminOrganization } from "@/lib/api";
import { formatBytes, formatDate } from "@/lib/format";

const PLAN_FILTER: Filter<AdminOrganization> = {
  id: "plan",
  label: "Plan",
  allLabel: "All plans",
  options: [
    { value: "free", label: "Free" },
    { value: "paid", label: "Paid" },
  ],
  test: (o, value) => (value === "paid" ? o.plan_id !== null : o.plan_id === null),
};

const columns: Column<AdminOrganization>[] = [
  {
    id: "name",
    header: "Workspace",
    hideLabelOnPhone: true,
    sortValue: (o) => o.name,
    cell: (o) => (
      <div className="min-w-0">
        <p className="truncate font-medium">
          {o.name}
          {o.deletion_scheduled_at && (
            <Badge tone="danger" className="ml-2">
              Deleting
            </Badge>
          )}
        </p>
        <p className="truncate text-xs text-ink-muted">{o.owner_email ?? "No owner"}</p>
      </div>
    ),
  },
  {
    id: "plan",
    header: "Plan",
    className: "sm:w-28",
    sortValue: (o) => o.plan_id ?? "",
    cell: (o) => (
      <Badge tone={o.plan_id ? "accent" : "neutral"}>
        {o.plan_id ?? "free"}
        {o.subscription_status && o.subscription_status !== "active"
          ? ` · ${o.subscription_status}`
          : ""}
      </Badge>
    ),
  },
  {
    id: "members",
    header: "People",
    align: "right",
    className: "sm:w-20 tabular",
    sortValue: (o) => o.members,
    cell: (o) => o.members,
  },
  {
    id: "storage",
    header: "Files",
    align: "right",
    className: "sm:w-24 tabular text-ink-muted",
    sortValue: (o) => o.storage_bytes,
    cell: (o) => formatBytes(o.storage_bytes),
  },
  {
    id: "jobs",
    header: "Jobs (month)",
    align: "right",
    className: "sm:w-28 tabular",
    sortValue: (o) => o.jobs_month,
    cell: (o) => o.jobs_month.toLocaleString("en"),
  },
  {
    id: "ai",
    header: "AI (month)",
    align: "right",
    className: "sm:w-32 tabular",
    sortValue: (o) => o.ai_cost_usd_month,
    cell: (o) => (
      <span title={`${o.ai_requests_month} requests`}>
        {o.ai_requests_month.toLocaleString("en")} · {formatUsd(o.ai_cost_usd_month)}
      </span>
    ),
  },
  {
    id: "created",
    header: "Created",
    className: "sm:w-32 text-ink-muted",
    sortValue: (o) => o.created_at,
    cell: (o) => <span className="tabular">{formatDate(o.created_at)}</span>,
  },
];

/** Admin → Workspaces: every workspace with owner, plan and this month's usage. */
export function AdminWorkspacesView() {
  const orgs = useApiData(async () => (await unwrap(api.GET("/api/admin/organizations"))).items);
  const table = useDataTable({
    rows: orgs.data,
    columns,
    searchText: (o) => `${o.name} ${o.owner_email ?? ""}`,
    filters: [PLAN_FILTER],
    initialSort: { id: "created", direction: "desc" },
    pageSize: 25,
  });
  if (orgs.data === null && orgs.error)
    return <Alert tone="error">Could not load: {orgs.error}</Alert>;
  return (
    <DataTable
      table={table}
      label="Workspaces"
      searchLabel="Search name or owner"
      rowKey={(o) => o.id}
      empty={
        <EmptyState
          icon={Building2}
          title="No workspaces yet"
          description="Every sign-up creates one. They appear here."
        />
      }
    />
  );
}
