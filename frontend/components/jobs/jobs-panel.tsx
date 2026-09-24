"use client";

import { Play, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { JobProgress, jobTitle } from "@/components/jobs/job-progress";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { isActive, useRecentJobs } from "@/hooks/use-jobs";
import type { Job } from "@/lib/api";

/** Announce when a job finishes (screen readers), without reading every progress tick. */
function useFinishAnnouncement(jobs: Job[] | null): string {
  const previous = useRef(new Map<string, Job["status"]>());
  const [announcement, setAnnouncement] = useState("");
  useEffect(() => {
    if (!jobs) return;
    for (const job of jobs) {
      const before = previous.current.get(job.id);
      if (before && before !== job.status && !isActive(job)) {
        setAnnouncement(`${jobTitle(job)} ${job.status === "done" ? "finished" : "failed"}.`);
      }
      previous.current.set(job.id, job.status);
    }
  }, [jobs]);
  return announcement;
}

/**
 * Dashboard section: start the example job and watch recent jobs update live.
 * Products copy this pattern for their own long tasks.
 */
export function JobsPanel() {
  const { jobs, loadError, starting, startError, startExample } = useRecentJobs();
  const announcement = useFinishAnnouncement(jobs);

  return (
    <section aria-labelledby="jobs-title" className="max-w-2xl">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-0.5">
          <h2 id="jobs-title" className="text-base font-semibold">
            Background jobs
          </h2>
          <p className="text-sm text-ink-muted">
            Long tasks run in a worker. Their progress updates here while they run.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={starting}
            onClick={() => void startExample({ steps: 4, fail: true })}
          >
            Run a job that fails
          </Button>
          <Button size="sm" disabled={starting} onClick={() => void startExample({ steps: 5 })}>
            <Play aria-hidden="true" />
            Run example job
          </Button>
        </div>
      </div>

      {startError && (
        <p role="alert" className="mb-3 flex items-start gap-2 text-sm text-danger">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {startError}
        </p>
      )}

      <div className="rounded-menu border border-line">
        {jobs === null && !loadError && (
          <ul className="divide-y divide-line">
            {[0, 1].map((i) => (
              <li key={i} className="space-y-2.5 px-4 py-3.5">
                <div className="flex items-center gap-3">
                  <Skeleton className="size-2 rounded-full" />
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="ml-auto h-4 w-12" />
                </div>
                <Skeleton className="h-1.5 w-full" />
              </li>
            ))}
          </ul>
        )}

        {jobs === null && loadError && (
          <p className="px-4 py-4 text-sm text-ink-muted">Could not load jobs: {loadError}</p>
        )}

        {jobs !== null && jobs.length === 0 && (
          <p className="px-4 py-6 text-sm text-ink-muted">
            No jobs yet. Run the example job to watch its progress here.
          </p>
        )}

        {jobs !== null && jobs.length > 0 && (
          <ul className="divide-y divide-line" aria-label="Recent jobs">
            {jobs.map((job) => (
              <li key={job.id} className="px-4 py-3.5">
                <JobProgress job={job} />
              </li>
            ))}
          </ul>
        )}
      </div>

      {jobs !== null && loadError && (
        <p className="mt-2 text-xs text-ink-muted">Could not refresh: {loadError}</p>
      )}
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
    </section>
  );
}
