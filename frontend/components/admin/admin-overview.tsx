"use client";

import { Pause, Play } from "lucide-react";
import { useState } from "react";

import { Section } from "@/components/settings/section";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { useApiData } from "@/hooks/use-api-data";
import { api, unwrap, type AdminOverview } from "@/lib/api";
import { formatBytes, formatDay } from "@/lib/format";

export function formatUsd(value: number): string {
  return value < 1 && value > 0
    ? `$${value.toFixed(4)}`
    : `$${value.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="space-y-1 rounded-menu border border-line p-4">
      <p className="text-sm text-ink-muted">{label}</p>
      <p className="text-lg font-semibold tabular">{value}</p>
      {note && <p className="text-xs text-ink-muted">{note}</p>}
    </div>
  );
}

/** Admin → Overview: headline numbers and the AI kill switch. */
export function AdminOverviewView() {
  const overview = useApiData(() => unwrap(api.GET("/api/admin/overview")));
  const data = overview.data;
  if (data === null && overview.error)
    return <Alert tone="error">Could not load: {overview.error}</Alert>;
  return (
    <div className="space-y-12">
      <section aria-label="Numbers" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {data === null ? (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)
        ) : (
          <>
            <Stat label="Users" value={data.users.toLocaleString("en")} />
            <Stat
              label="Workspaces"
              value={data.workspaces.toLocaleString("en")}
              note={`${data.paid_workspaces.toLocaleString("en")} on a paid plan`}
            />
            <Stat
              label="AI this month"
              value={formatUsd(data.ai_cost_usd_month)}
              note={`${data.ai_requests_month.toLocaleString("en")} requests since ${formatDay(data.month)}`}
            />
            <Stat
              label="Failed jobs (7 days)"
              value={data.failed_jobs_7d.toLocaleString("en")}
              note={`${formatBytes(data.storage_bytes)} of files stored`}
            />
          </>
        )}
      </section>
      {data && <AiSwitch data={data} onChange={(next) => overview.setData(next)} />}
    </div>
  );
}

function AiSwitch({
  data,
  onChange,
}: {
  data: AdminOverview;
  onChange: (next: AdminOverview) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const paused = data.ai_paused;

  async function set(nextPaused: boolean) {
    const next = await unwrap(api.PUT("/api/admin/ai", { body: { paused: nextPaused } }));
    onChange(next);
    toast.success(nextPaused ? "All AI features are paused." : "AI features are on again.");
  }

  return (
    <Section
      title="AI kill switch"
      description="Pausing stops every AI request in every workspace at once (no restart). Use it when costs run away or the model misbehaves."
    >
      <div className="flex flex-wrap items-center gap-3 rounded-menu border border-line p-4">
        <Badge tone={paused ? "danger" : "success"}>{paused ? "Paused" : "Running"}</Badge>
        <span className="min-w-0 flex-1 text-sm text-ink-muted">
          Model provider: <strong className="text-ink">{data.ai_provider}</strong>
          {data.ai_provider === "fake" && " (pretend model for local development)"}
          {data.ai_provider === "none" && " (no OPENAI_API_KEY: AI is off)"}
        </span>
        {paused ? (
          <Button onClick={() => void set(false).catch((e: Error) => toast.error(e.message))}>
            <Play aria-hidden="true" />
            Resume AI
          </Button>
        ) : (
          <Button variant="danger-outline" onClick={() => setConfirming(true)}>
            <Pause aria-hidden="true" />
            Pause all AI
          </Button>
        )}
      </div>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Pause all AI features?"
        description="Every AI request in every workspace is refused until you resume. People see “AI features are paused right now”."
        confirmLabel="Pause AI"
        busyLabel="Pausing…"
        onConfirm={() => set(true)}
      />
    </Section>
  );
}
