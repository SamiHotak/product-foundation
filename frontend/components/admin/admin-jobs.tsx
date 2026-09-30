"use client";

import { CircleCheck, RotateCcw } from "lucide-react";
import { useState } from "react";

import { jobTitle } from "@/components/jobs/job-progress";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { toast } from "@/components/ui/toast";
import { useApiData } from "@/hooks/use-api-data";
import { useDataTable, type Column } from "@/hooks/use-data-table";
import { api, errorMessage, unwrap, type AdminFailedJob } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

/** Admin → Failed jobs (the dead-letter list): see why, and run them again. */
export function AdminJobsView() {
  const jobs = useApiData(async () => (await unwrap(api.GET("/api/admin/jobs/failed"))).items);
  const [busy, setBusy] = useState<string | null>(null);

  async function retry(job: AdminFailedJob) {
    setBusy(job.id);
    try {
      await unwrap(
        api.POST("/api/admin/jobs/{job_id}/retry", { params: { path: { job_id: job.id } } }),
      );
      toast.success(`${jobTitle(job)} queued again.`);
      jobs.setData((prev) => prev?.filter((j) => j.id !== job.id) ?? null);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const columns: Column<AdminFailedJob>[] = [
    {
      id: "job",
      header: "Job",
      hideLabelOnPhone: true,
      sortValue: (j) => j.kind,
      cell: (j) => (
        <div className="min-w-0 space-y-0.5">
          <p className="font-medium">
            {jobTitle(j)}{" "}
            <span className="font-normal text-ink-muted">in {j.organization_name}</span>
          </p>
          <p className="text-sm break-words text-danger">{j.error ?? "No error message"}</p>
          <p className="text-xs text-ink-muted">
            {j.started_by ?? "Started by the system"} · {j.attempts}{" "}
            {j.attempts === 1 ? "attempt" : "attempts"}
          </p>
        </div>
      ),
    },
    {
      id: "finished",
      header: "Failed",
      className: "sm:w-44 text-ink-muted",
      sortValue: (j) => j.finished_at,
      cell: (j) => (j.finished_at ? formatDateTime(j.finished_at) : "-"),
    },
    {
      id: "actions",
      header: "",
      align: "right",
      className: "sm:w-28 max-sm:justify-end",
      cell: (j) => (
        <Button
          variant="secondary"
          size="sm"
          disabled={busy === j.id}
          onClick={() => void retry(j)}
        >
          <RotateCcw aria-hidden="true" />
          Retry
        </Button>
      ),
    },
  ];

  const table = useDataTable({
    rows: jobs.data,
    columns,
    searchText: (j) => `${j.kind} ${j.organization_name} ${j.error ?? ""} ${j.started_by ?? ""}`,
    initialSort: { id: "finished", direction: "desc" },
    pageSize: 25,
  });
  if (jobs.data === null && jobs.error)
    return <Alert tone="error">Could not load: {jobs.error}</Alert>;
  return (
    <DataTable
      table={table}
      label="Failed jobs"
      searchLabel="Search kind, workspace or error"
      rowKey={(j) => j.id}
      empty={
        <EmptyState
          icon={CircleCheck}
          title="No failed jobs"
          description="Jobs that fail after all their retries show up here, with the reason."
        />
      }
    />
  );
}
