"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";

import { ApiErrorAlert } from "@/components/billing/api-error-alert";
import { JobProgress } from "@/components/jobs/job-progress";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiData } from "@/hooks/use-api-data";
import { useJob } from "@/hooks/use-jobs";
import { api, errorMessage, unwrap } from "@/lib/api";

const MIN = 20;
const MAX = 5000;

/** What the ai_summary job returns (backend/app/workers/tasks.py). */
type SummaryResult = {
  summary: { title: string; key_points: string[]; language: string };
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
};

function isSummaryResult(value: unknown): value is SummaryResult {
  return typeof value === "object" && value !== null && "summary" in value;
}

function formatUsd(value: number): string {
  if (value === 0) return "$0";
  return value < 0.01 ? `$${value.toFixed(5)}` : `$${value.toFixed(2)}`;
}

/**
 * The example AI feature: summarize a text. It shows the whole pattern products use:
 * start a background job -> follow it live -> show the structured result, with plan
 * limits ("limit reached"), the kill switch ("AI is paused") and costs.
 */
export function SummaryPanel() {
  const status = useApiData(() => unwrap(api.GET("/api/ai/status")));
  const [text, setText] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<{ message: string; cause: unknown } | null>(null);
  const [starting, setStarting] = useState(false);
  const { job } = useJob(jobId);

  const length = text.trim().length;
  const ready = status.data?.available && status.data.can_use;
  // The shared demo may only summarize the sample (visitors share one account).
  const samplesOnly = status.data?.samples_only ?? false;

  async function start(event: React.FormEvent) {
    event.preventDefault();
    if (length < MIN) {
      setError({ message: `Write at least ${MIN} characters.`, cause: null });
      return;
    }
    setStarting(true);
    setError(null);
    try {
      const created = await unwrap(api.POST("/api/ai/summaries", { body: { text: text.trim() } }));
      setJobId(created.id);
    } catch (err) {
      setError({ message: errorMessage(err), cause: err });
      void status.reload(); // e.g. AI was paused in the meantime
    } finally {
      setStarting(false);
    }
  }

  const result = job?.status === "done" && isSummaryResult(job.result) ? job.result : null;

  return (
    <section id="ai" aria-labelledby="ai-title" className="max-w-2xl scroll-mt-6 space-y-3">
      <div className="space-y-0.5">
        <h2 id="ai-title" className="text-base font-semibold">
          AI summary
        </h2>
        <p className="text-sm text-ink-muted">
          The example AI feature. It runs as a background job through the LLM gateway, which counts
          it against the plan and records its cost.
        </p>
      </div>

      {status.data === null && !status.error && <Skeleton className="h-32 w-full" />}
      {status.data && !status.data.available && (
        <Alert>{status.data.reason ?? "AI is not available right now."}</Alert>
      )}
      {status.data?.provider === "fake" && status.data.available && (
        <p className="text-xs text-ink-muted" data-testid="ai-pretend">
          Local pretend model: answers are simple and free. Put OPENAI_API_KEY in backend/.env for
          the real model.
        </p>
      )}

      {status.data && (
        <form onSubmit={start} className="space-y-3" aria-label="Summarize a text">
          <label htmlFor="ai-text" className="sr-only">
            Text to summarize
          </label>
          <textarea
            id="ai-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={MAX}
            rows={5}
            disabled={!ready}
            readOnly={samplesOnly}
            placeholder={
              samplesOnly
                ? "In the demo, click “Use a sample text”."
                : "Paste meeting notes, an email or a short article…"
            }
            className="block w-full resize-y rounded-control border border-line-strong bg-surface px-3 py-2 text-sm placeholder:text-ink-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="submit"
              disabled={!ready || starting || (job !== null && !job.finished_at)}
            >
              <Sparkles aria-hidden="true" />
              {starting ? "Starting…" : "Summarize"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={!ready}
              onClick={() => {
                setText(status.data?.sample_text ?? "");
                setError(null);
              }}
            >
              Use a sample text
            </Button>
            {samplesOnly && (
              <span className="text-xs text-ink-muted">
                Demo: sample text only. Your own account can summarize any text.
              </span>
            )}
            <span className="ml-auto text-xs text-ink-muted tabular">
              {length.toLocaleString("en")} / {MAX.toLocaleString("en")}
            </span>
          </div>
        </form>
      )}

      {error && <ApiErrorAlert message={error.message} cause={error.cause} />}
      {job && !result && (
        <div className="rounded-menu border border-line p-4">
          <JobProgress job={job} />
        </div>
      )}
      {result && (
        <article
          className="space-y-3 rounded-menu border border-line p-4"
          data-testid="ai-summary"
          lang={result.summary.language}
        >
          <h3 className="font-semibold">{result.summary.title}</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {result.summary.key_points.map((point, index) => (
              <li key={index}>{point}</li>
            ))}
          </ul>
          <p className="text-xs text-ink-muted tabular" lang="en">
            {result.model} · {result.input_tokens + result.output_tokens} tokens ·{" "}
            {formatUsd(result.cost_usd)} · {(result.latency_ms / 1000).toFixed(1)} s
          </p>
        </article>
      )}
    </section>
  );
}
