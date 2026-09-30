"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";

import { formatUsd } from "@/components/admin/admin-overview";
import { Alert } from "@/components/ui/alert";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { useApiData } from "@/hooks/use-api-data";
import { useDataTable, type Column } from "@/hooks/use-data-table";
import { api, unwrap, type AdminAiUsageRow } from "@/lib/api";

const columns: Column<AdminAiUsageRow>[] = [
  {
    id: "workspace",
    header: "Workspace",
    hideLabelOnPhone: true,
    sortValue: (r) => r.organization_name,
    cell: (r) => <span className="font-medium">{r.organization_name}</span>,
  },
  {
    id: "task",
    header: "Task · model",
    className: "sm:w-56 text-ink-muted",
    sortValue: (r) => `${r.task} ${r.model}`,
    cell: (r) => (
      <span>
        {r.task} · <span className="font-mono text-xs">{r.model}</span>
      </span>
    ),
  },
  {
    id: "requests",
    header: "Requests",
    align: "right",
    className: "sm:w-28 tabular",
    sortValue: (r) => r.requests,
    cell: (r) => (
      <span>
        {r.requests.toLocaleString("en")}
        {r.failed > 0 && <span className="text-danger"> ({r.failed} failed)</span>}
      </span>
    ),
  },
  {
    id: "tokens",
    header: "Tokens in / out",
    align: "right",
    className: "sm:w-40 tabular text-ink-muted",
    sortValue: (r) => r.input_tokens + r.output_tokens,
    cell: (r) => `${r.input_tokens.toLocaleString("en")} / ${r.output_tokens.toLocaleString("en")}`,
  },
  {
    id: "cost",
    header: "Cost",
    align: "right",
    className: "sm:w-28 tabular",
    sortValue: (r) => r.cost_usd,
    cell: (r) => formatUsd(r.cost_usd),
  },
];

function thisMonth(): string {
  const now = new Date();
  return `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
}

/** Admin → AI usage: requests, tokens and cost per workspace, task and model. */
export function AdminUsageView() {
  const [month, setMonth] = useState(thisMonth);
  return (
    <div className="space-y-4">
      <label className="block w-44 space-y-1 text-sm">
        <span className="block font-medium">Month (UTC)</span>
        <Input
          type="month"
          value={month}
          max={thisMonth()}
          onChange={(e) => e.target.value && setMonth(e.target.value)}
        />
      </label>
      {/* key: a new month = a fresh load */}
      <MonthUsage key={month} month={month} />
    </div>
  );
}

function MonthUsage({ month }: { month: string }) {
  const usage = useApiData(() =>
    unwrap(api.GET("/api/admin/usage", { params: { query: { month: `${month}-01` } } })),
  );
  const table = useDataTable({
    rows: usage.data?.rows ?? null,
    columns,
    searchText: (r) => `${r.organization_name} ${r.task} ${r.model}`,
    initialSort: { id: "cost", direction: "desc" },
    pageSize: 25,
  });
  return (
    <div className="space-y-3">
      {usage.data && (
        <p className="text-sm text-ink-muted" data-testid="usage-total">
          {usage.data.total_requests.toLocaleString("en")} requests ·{" "}
          <strong className="text-ink">{formatUsd(usage.data.total_cost_usd)}</strong>
        </p>
      )}
      {usage.error && <Alert tone="error">Could not load: {usage.error}</Alert>}
      <DataTable
        table={table}
        label="AI usage"
        searchLabel="Search workspace, task or model"
        rowKey={(r) => `${r.organization_id}-${r.task}-${r.model}`}
        empty={
          <EmptyState
            icon={Sparkles}
            title="No AI requests in this month"
            description="Every call through the LLM gateway is counted here with its cost. Traces with prompts and answers are in Langfuse."
          />
        }
      />
    </div>
  );
}
