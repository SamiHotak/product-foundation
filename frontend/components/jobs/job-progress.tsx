"use client";

import { useEffect, useState } from "react";

import { ProgressBar } from "@/components/ui/progress-bar";
import { StatusDot } from "@/components/ui/status-dot";
import type { Job, JobStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS: Record<
  JobStatus,
  {
    label: string;
    dot: "pending" | "active" | "ok" | "error";
    bar: "muted" | "accent" | "danger";
  }
> = {
  queued: { label: "Waiting", dot: "pending", bar: "muted" },
  running: { label: "Running", dot: "active", bar: "accent" },
  done: { label: "Done", dot: "ok", bar: "accent" },
  failed: { label: "Failed", dot: "error", bar: "danger" },
};

/** Names people understand for each job kind. Products add their own kinds here. */
const KIND_LABELS: Record<string, string> = {
  example: "Example job",
  data_export: "Data export",
};

export function jobTitle(job: Pick<Job, "kind">): string {
  return KIND_LABELS[job.kind] ?? job.kind;
}

function formatSeconds(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${s % 60} s`;
}

/** Re-render every second while `active`, so elapsed time counts up smoothly. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

function timing(job: Job, now: number): string | null {
  if (job.started_at && job.finished_at) {
    const took = (Date.parse(job.finished_at) - Date.parse(job.started_at)) / 1000;
    return `Took ${formatSeconds(took)}`;
  }
  if (job.started_at) return formatSeconds((now - Date.parse(job.started_at)) / 1000);
  return null;
}

/**
 * Live status of one background job: state, progress bar, what it is doing now,
 * and the error text if it failed. Reusable in every product.
 */
export function JobProgress({ job, className }: { job: Job; className?: string }) {
  const status = STATUS[job.status];
  const now = useNow(job.status === "running");
  const time = timing(job, now);
  const title = jobTitle(job);
  const detail = job.status === "failed" ? job.error : job.message;

  return (
    <div className={cn("space-y-2", className)} data-job-id={job.id} data-job-status={job.status}>
      <div className="flex items-center gap-3 text-sm">
        <StatusDot tone={status.dot} />
        <span className="font-medium">{title}</span>
        <span className="text-ink-muted">{status.label}</span>
        <span className="ml-auto text-ink-muted tabular">
          {time}
          {job.status !== "failed" && (
            <span
              className={cn(
                "ml-3 inline-block w-10 text-right",
                job.status === "done" && "text-success",
              )}
            >
              {job.progress}%
            </span>
          )}
        </span>
      </div>
      {/* A finished job needs no bar; a failed one keeps it to show where it stopped. */}
      {job.status !== "done" && (
        <ProgressBar
          value={job.status === "failed" ? Math.max(job.progress, 4) : job.progress}
          tone={status.bar}
          label={`${title}: ${status.label.toLowerCase()}, ${job.progress}%`}
        />
      )}
      {detail && (
        <p className={cn("text-sm", job.status === "failed" ? "text-danger" : "text-ink-muted")}>
          {detail}
          {job.attempts > 1 && job.status !== "done" && (
            <span className="text-ink-muted"> (attempt {job.attempts})</span>
          )}
        </p>
      )}
    </div>
  );
}
