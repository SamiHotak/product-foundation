"use client";

import { CircleCheck, Circle, PartyPopper, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ProgressBar } from "@/components/ui/progress-bar";
import { toast } from "@/components/ui/toast";
import { product } from "@/config/product";
import { api, errorMessage, unwrap, type Onboarding } from "@/lib/api";
import { ONBOARDING_REFRESH } from "@/lib/events";
import { cn } from "@/lib/utils";

/**
 * "Get started" checklist on the dashboard. Which steps are done comes from the API
 * (backend/app/services/onboarding.py); titles, texts and links from config/product.ts.
 * Hidden per person and per workspace, with Undo.
 */
export function OnboardingChecklist({ initial }: { initial: Onboarding | null }) {
  const [status, setStatus] = useState(initial);

  useEffect(() => {
    // Re-check after actions on this page, and when coming back to the tab.
    const refresh = () => {
      unwrap(api.GET("/api/organizations/current/onboarding"))
        .then(setStatus)
        .catch(() => null); // keep what we show; the checklist is not critical
    };
    const onVisible = () => document.visibilityState === "visible" && refresh();
    window.addEventListener(ONBOARDING_REFRESH, refresh);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener(ONBOARDING_REFRESH, refresh);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  if (!status || status.dismissed) return null;

  const done = new Map(status.steps.map((s) => [s.key, s.done]));
  // Config order; only steps the API returned (it leaves out steps you may not do).
  const steps = product.onboarding.filter((item) => done.has(item.key));
  if (steps.length === 0) return null;
  const finished = steps.filter((item) => done.get(item.key)).length;
  const allDone = finished === steps.length;

  async function hide() {
    const before = status;
    setStatus((s) => (s ? { ...s, dismissed: true } : s)); // optimistic
    try {
      await unwrap(api.POST("/api/organizations/current/onboarding/dismiss"));
      toast("Checklist hidden.", {
        description: "Bring it back from Settings → Profile.",
        action: { label: "Undo", onClick: () => void restore() },
      });
    } catch (err) {
      setStatus(before);
      toast.error("Could not hide the checklist.", { description: errorMessage(err) });
    }
  }

  async function restore() {
    try {
      setStatus(await unwrap(api.DELETE("/api/organizations/current/onboarding/dismiss")));
    } catch (err) {
      toast.error("Could not show the checklist again.", { description: errorMessage(err) });
    }
  }

  return (
    <section
      aria-labelledby="onboarding-title"
      className="max-w-2xl rounded-menu border border-line bg-surface-sunken/40 p-5"
    >
      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1 space-y-1">
          <h2 id="onboarding-title" className="flex items-center gap-2 text-base font-semibold">
            {allDone && <PartyPopper className="size-4 text-accent" aria-hidden="true" />}
            {allDone ? "You're all set" : "Get started"}
          </h2>
          <p className="text-sm text-ink-muted">
            {allDone
              ? `You have tried everything ${product.name} offers here. You can hide this now.`
              : `${finished} of ${steps.length} done. A few minutes to get the most out of ${product.name}.`}
          </p>
        </div>
        <Button
          variant="ghost"
          size={allDone ? "sm" : "icon"}
          className={allDone ? undefined : "size-8"}
          aria-label="Hide checklist"
          onClick={() => void hide()}
        >
          {allDone ? "Hide checklist" : <X />}
        </Button>
      </div>
      <ProgressBar
        value={(finished / steps.length) * 100}
        label="Get started progress"
        tone={allDone ? "success" : "accent"}
        className="mt-4"
      />
      <ol className="mt-4 space-y-1" aria-label="Steps">
        {steps.map((item) => {
          const isDone = done.get(item.key) === true;
          return (
            <li
              key={item.key}
              data-step={item.key}
              data-done={isDone}
              className={cn(
                "flex items-start gap-3 rounded-control px-2 py-2.5",
                !isDone && "bg-surface",
              )}
            >
              {isDone ? (
                <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" aria-hidden="true" />
              ) : (
                <Circle className="mt-0.5 size-4 shrink-0 text-line-strong" aria-hidden="true" />
              )}
              <div className="min-w-0 flex-1">
                <p className={cn("text-sm font-medium", isDone && "text-ink-muted")}>
                  {item.title}
                  <span className="sr-only">{isDone ? " (done)" : " (to do)"}</span>
                </p>
                {!isDone && <p className="text-sm text-ink-muted">{item.description}</p>}
              </div>
              {!isDone && (
                <Button asChild variant="secondary" size="sm">
                  <Link href={item.href}>{item.action}</Link>
                </Button>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
