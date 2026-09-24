"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage, unwrap, type ExampleJobCreate, type Job } from "@/lib/api";

/** Queued or running: the job will still change. */
export function isActive(job: Pick<Job, "status">): boolean {
  return job.status === "queued" || job.status === "running";
}

/**
 * Call `tick` every `intervalMs` while `enabled` is true (with `immediate`, also
 * right away). Waits for each tick to finish before scheduling the next (no
 * pile-up on slow networks) and skips ticks while the browser tab is hidden.
 */
function usePolling(
  tick: () => Promise<void>,
  enabled: boolean,
  intervalMs: number,
  immediate = false,
) {
  const tickRef = useRef(tick);
  useEffect(() => {
    tickRef.current = tick;
  }, [tick]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => {
      if (!document.hidden) await tickRef.current();
      if (!cancelled) timer = setTimeout(loop, intervalMs);
    };
    timer = setTimeout(loop, immediate ? 0 : intervalMs);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [enabled, intervalMs, immediate]);
}

type RecentJobsState = {
  jobs: Job[] | null;
  loadError: string | null;
};

/**
 * Recent jobs with live status. Polls while any job is queued or running,
 * and stops polling when everything has finished.
 */
export function useRecentJobs({ limit = 8, intervalMs = 1000 } = {}) {
  const [state, setState] = useState<RecentJobsState>({ jobs: null, loadError: null });
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await unwrap(api.GET("/api/jobs", { params: { query: { limit } } }));
      setState({ jobs: data.items, loadError: null });
    } catch (err) {
      setState((prev) => ({ ...prev, loadError: errorMessage(err) }));
    }
  }, [limit]);

  useEffect(() => {
    // Initial load (data fetching from an external system).
    void load();
  }, [load]);

  const hasActive = state.jobs?.some(isActive) ?? false;
  usePolling(load, hasActive, intervalMs);

  const startExample = useCallback(
    async (body: ExampleJobCreate) => {
      setStarting(true);
      setStartError(null);
      try {
        const job = await unwrap(api.POST("/api/jobs/example", { body }));
        // Show the new job immediately; polling takes over from here.
        setState((prev) => ({
          ...prev,
          jobs: [job, ...(prev.jobs ?? []).filter((j) => j.id !== job.id)].slice(0, limit),
        }));
        return job;
      } catch (err) {
        setStartError(errorMessage(err));
        return null;
      } finally {
        setStarting(false);
      }
    },
    [limit],
  );

  return { ...state, starting, startError, startExample, reload: load };
}

/**
 * One job with live status, polled until it is done or failed.
 * Use it after starting a job from a product feature (upload, import, report, ...).
 */
export function useJob(jobId: string | null, { intervalMs = 1000 } = {}) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!jobId) return;
    try {
      setJob(await unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: jobId } } })));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [jobId]);

  // Loads right away, then keeps polling until the job is done or failed.
  const current = job?.id === jobId ? job : null;
  usePolling(load, jobId !== null && (current === null || isActive(current)), intervalMs, true);

  return { job: current, error, reload: load };
}
