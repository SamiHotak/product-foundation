"use client";

import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusDot } from "@/components/ui/status-dot";
import { ApiError, apiGet, type ReadinessResponse } from "@/lib/api";

const LABELS: Record<string, string> = { database: "Database", redis: "Redis (queue and cache)" };

type State =
  | { kind: "loading" }
  | { kind: "ready"; data: ReadinessResponse; checkedAt: Date }
  | { kind: "failed"; message: string };

/** Live view of /api/health/ready: is the API up, and can it reach Postgres and Redis? */
export function SystemStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await apiGet<ReadinessResponse>("/health/ready", {
        cache: "no-store",
        acceptStatuses: [503],
      });
      setState({ kind: "ready", data, checkedAt: new Date() });
    } catch (err) {
      const message =
        err instanceof ApiError && err.status !== 0
          ? `The API answered with an error (${err.status}). Check the backend logs: make logs`
          : "The API is not reachable. Start it with: make dev";
      setState({ kind: "failed", message });
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    // Initial load when the component mounts (data fetching from an external system).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  return (
    <section aria-labelledby="status-title" className="max-w-2xl">
      <div className="mb-3 flex items-center justify-between gap-4">
        <h2 id="status-title" className="text-base font-semibold">
          System status
        </h2>
        <Button variant="secondary" size="sm" onClick={() => void load()} disabled={refreshing}>
          <RefreshCw className={refreshing ? "animate-spin" : undefined} aria-hidden="true" />
          Check again
        </Button>
      </div>

      <div className="rounded-menu border border-line" aria-live="polite" aria-busy={refreshing}>
        {state.kind === "loading" && (
          <ul className="divide-y divide-line">
            {[0, 1, 2].map((i) => (
              <li key={i} className="flex items-center gap-3 px-4 py-3">
                <Skeleton className="size-2 rounded-full" />
                <Skeleton className="h-4 w-40" />
                <Skeleton className="ml-auto h-4 w-16" />
              </li>
            ))}
          </ul>
        )}

        {state.kind === "failed" && (
          <div className="flex items-start gap-3 px-4 py-4">
            <StatusDot tone="error" className="mt-1.5" />
            <div className="space-y-0.5">
              <p className="text-sm font-medium">API not available</p>
              <p className="text-sm text-ink-muted">{state.message}</p>
            </div>
          </div>
        )}

        {state.kind === "ready" && (
          <ul className="divide-y divide-line">
            <StatusRow label="API" ok detail={`v${state.data.version}`} />
            {state.data.checks.map((check) => (
              <StatusRow
                key={check.name}
                label={LABELS[check.name] ?? check.name}
                ok={check.status === "ok"}
                detail={
                  check.status === "ok"
                    ? `${Math.round(check.latency_ms ?? 0)} ms`
                    : `Down: ${check.error ?? "unknown error"}`
                }
              />
            ))}
          </ul>
        )}
      </div>

      {state.kind === "ready" && (
        <p className="mt-2 text-xs text-ink-muted">
          Environment: {state.data.environment}. Last checked{" "}
          <time dateTime={state.checkedAt.toISOString()} className="tabular">
            {state.checkedAt.toLocaleTimeString()}
          </time>
          .
        </p>
      )}
    </section>
  );
}

function StatusRow({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <li className="flex items-center gap-3 px-4 py-3 text-sm">
      <StatusDot tone={ok ? "ok" : "error"} />
      <span className="font-medium">{label}</span>
      <span className="sr-only">{ok ? "working" : "not working"}</span>
      <span className={`ml-auto tabular ${ok ? "text-ink-muted" : "text-danger"}`}>{detail}</span>
    </li>
  );
}
