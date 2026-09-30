"use client";

import { Check, CreditCard, ExternalLink, Receipt } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { formatPrice, monthsFree } from "@/components/marketing/pricing";
import { useSession } from "@/components/session-provider";
import { NoAccess, Section } from "@/components/settings/section";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ProgressBar } from "@/components/ui/progress-bar";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { useApiData } from "@/hooks/use-api-data";
import {
  api,
  errorMessage,
  unwrap,
  type BillingInterval,
  type BillingOverview,
  type Plan,
  type Plans,
  type UsageItem,
} from "@/lib/api";
import { formatDate, formatDay } from "@/lib/format";
import { legal } from "@/config/legal";
import { cn } from "@/lib/utils";

type Return = "confirming" | "slow" | "cancelled" | null;

const CONFIRM_TRIES = 20; // x 1.5 s: Stripe's webhook usually arrives within seconds

/**
 * Settings → Billing (owner): plan and status, usage against the limits, choose a plan
 * (Stripe Checkout), and "Manage billing" (Stripe's portal: card, invoices, VAT ID, change
 * plan, cancel). After checkout Stripe sends people back here with ?checkout=success; the
 * plan changes when Stripe's webhook arrives, so the page waits for it.
 */
export function BillingSettings() {
  const { can, activeOrganization } = useSession();
  const allowed = can("billing:manage");
  const router = useRouter();
  const overview = useApiData(async () =>
    allowed ? await unwrap(api.GET("/api/billing/current")) : null,
  );
  const plans = useApiData(async () => await unwrap(api.GET("/api/billing/plans")));
  const [returned, setReturned] = useState<Return>(null);
  const [wanted, setWanted] = useState<string | null>(null);

  // Read ?checkout= and ?plan= once, then clean the address bar.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const checkout = params.get("checkout");
    const plan = params.get("plan");
    if (!checkout && !plan) return;
    // One-time read of the URL on arrival (an external system: the browser address bar).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (checkout === "success") setReturned("confirming");
    if (checkout === "cancelled") setReturned("cancelled");
    if (plan) setWanted(plan);
    router.replace("/settings/billing", { scroll: false });
  }, [router]);

  const reloadOverview = overview.reload;
  const tries = useRef(0);
  const [tick, setTick] = useState(0);
  const paid = overview.data !== null && isPaid(overview.data);
  useEffect(() => {
    if (returned !== "confirming") return;
    if (paid) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- the wait is over
      setReturned(null);
      toast.success(`Thank you! “${activeOrganization.name}” is on the new plan.`);
      return;
    }
    const timer = window.setTimeout(() => {
      tries.current += 1;
      if (tries.current >= CONFIRM_TRIES) setReturned("slow");
      else void reloadOverview().finally(() => setTick((t) => t + 1));
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [returned, paid, tick, reloadOverview, activeOrganization.name]);

  if (!allowed) {
    return <NoAccess>Only the owner of this workspace manages billing.</NoAccess>;
  }
  const data = overview.data;
  return (
    <div className="space-y-12">
      {returned === "confirming" && (
        <Alert>Confirming your payment with Stripe. This takes a few seconds…</Alert>
      )}
      {returned === "slow" && (
        <Alert>
          Stripe has not confirmed the payment yet. If you paid, the plan appears here in a minute.
          Refresh the page to check.
        </Alert>
      )}
      {returned === "cancelled" && <Alert>Checkout cancelled. Nothing was charged.</Alert>}
      {data?.provider === "dev" && (
        <Alert>
          Test mode: checkout and the billing portal are pretend pages. No real payment happens.
        </Alert>
      )}

      <Section title="Plan" description={`The plan of “${activeOrganization.name}”.`}>
        {data === null ? (
          overview.error ? (
            <Alert tone="error">Could not load billing: {overview.error}</Alert>
          ) : (
            <Skeleton className="h-28 w-full" />
          )
        ) : (
          <CurrentPlan overview={data} plans={plans.data} />
        )}
      </Section>

      <Section
        title="Usage"
        description={
          data ? `Monthly counters start again on ${formatDay(data.usage_resets_on)}.` : undefined
        }
      >
        {data === null ? <Skeleton className="h-24 w-full" /> : <UsageMeters usage={data.usage} />}
      </Section>

      {data && data.provider === "none" && (
        <Section title="Change plan">
          <Alert>Paid plans are not available yet.</Alert>
        </Section>
      )}
      {data && data.provider !== "none" && (
        <Section
          title="Change plan"
          id="change-plan"
          description={
            paid
              ? "To switch plan, pay yearly instead of monthly, or cancel, open Manage billing."
              : "Pick a plan. You pay on Stripe's secure page; we never see your card."
          }
        >
          {paid ? (
            <PortalButton label="Change or cancel plan" variant="secondary" />
          ) : (
            <PlanPicker overview={data} plans={plans.data} wanted={wanted} />
          )}
        </Section>
      )}

      {data && data.provider !== "none" && (
        <Section title="Invoices and payment method">
          {data.has_billing_account ? (
            <div className="flex flex-wrap items-center gap-4 rounded-menu border border-line p-5">
              <Receipt className="size-5 text-ink-muted" aria-hidden="true" />
              <p className="min-w-56 flex-1 text-sm text-ink-muted">
                Invoices (PDF), your card and your VAT ID are managed on Stripe. Stripe also emails
                a receipt for every payment.
              </p>
              <PortalButton label="Open invoices" variant="secondary" />
            </div>
          ) : (
            <EmptyState
              icon={CreditCard}
              title="No payment method"
              description="Not needed on the free plan. Card details are handled by Stripe and never stored by us."
            />
          )}
        </Section>
      )}
    </div>
  );
}

function isPaid(o: BillingOverview): boolean {
  return o.status === "trialing" || o.status === "active" || o.status === "past_due";
}

function priceOf(plans: Plans | null, o: BillingOverview): string | null {
  const plan = plans?.plans.find((p) => p.id === o.plan_id);
  if (!plans || !plan || !o.interval) return null;
  const cents = o.interval === "year" ? plan.price_yearly : plan.price_monthly;
  return `${formatPrice(cents, plans.currency)} a ${o.interval}`;
}

function CurrentPlan({ overview: o, plans }: { overview: BillingOverview; plans: Plans | null }) {
  const paid = isPaid(o);
  const price = priceOf(plans, o);
  const end = o.current_period_end ? formatDate(o.current_period_end) : null;
  let badge: { text: string; tone: "accent" | "success" | "warning" | "danger" } = {
    text: "Current plan",
    tone: "accent",
  };
  let line = "Upgrade any time. Nothing is charged without your OK.";
  if (o.status === "trialing") {
    badge = { text: "Free trial", tone: "accent" };
    line = o.trial_end
      ? `Free until ${formatDate(o.trial_end)}${price ? `, then ${price}` : ""}.`
      : "Free trial.";
  } else if (o.status === "active") {
    badge = { text: "Active", tone: "success" };
    line = `${price ? `${price}. ` : ""}${end ? `Renews on ${end}.` : ""}`;
  } else if (o.status === "past_due") {
    badge = { text: "Payment failed", tone: "danger" };
    line = "Stripe will try again over the next days.";
  }
  if (paid && o.cancel_at_period_end) {
    badge = { text: "Ends soon", tone: "warning" };
    line = `Cancelled: you keep ${o.plan_name} until ${end ?? "the end of the period"}. No further charges.`;
  }
  return (
    <div className="space-y-4">
      {o.status === "past_due" && (
        <Alert tone="error">
          Your last payment failed. Update your payment method so “{o.plan_name}” stays active.
        </Alert>
      )}
      <div
        className="flex flex-wrap items-start gap-4 rounded-menu border border-line p-5"
        data-testid="current-plan"
      >
        <div className="min-w-0 flex-1 space-y-1">
          <p className="flex flex-wrap items-center gap-2 font-semibold">
            {o.plan_name} <Badge tone={badge.tone}>{badge.text}</Badge>
          </p>
          <p className="max-w-prose text-sm text-ink-muted">{line}</p>
        </div>
        {o.has_billing_account && paid && <PortalButton label="Manage billing" />}
      </div>
    </div>
  );
}

/** Counters that start again every month (reaching them stops the work until then). */
const MONTHLY = new Set(["jobs_per_month", "ai_requests_per_month"]);

/** "1,234" or, for storage, "250 MB" / "10 GB". */
function amount(value: number, unit: UsageItem["unit"]): string {
  if (unit !== "mb") return value.toLocaleString("en");
  return value >= 1024
    ? `${(value / 1024).toLocaleString("en", { maximumFractionDigits: 1 })} GB`
    : `${value.toLocaleString("en")} MB`;
}

function UsageMeters({ usage }: { usage: UsageItem[] }) {
  return (
    <ul className="grid gap-4 sm:grid-cols-3" aria-label="Usage">
      {usage.map((u) => {
        const unlimited = u.limit === null || u.limit === undefined;
        const limit = u.limit ?? 0;
        const percent = unlimited ? 0 : limit === 0 ? 100 : (u.used / limit) * 100;
        const over = !unlimited && u.used > limit;
        const full = !unlimited && u.used >= limit;
        // Monthly usage at the limit blocks work; people/keys/files at the limit only block adding.
        const monthly = MONTHLY.has(u.metric);
        const blocking = over || (full && monthly);
        const note = over
          ? "Over the plan limit: remove some or upgrade"
          : full
            ? monthly
              ? "Limit reached"
              : "All used: upgrade to add more"
            : null;
        return (
          <li
            key={u.metric}
            data-metric={u.metric}
            className="space-y-2.5 rounded-menu border border-line p-4"
          >
            <p className="text-sm text-ink-muted">{u.label}</p>
            <p className="text-lg font-semibold tabular">
              {amount(u.used, u.unit)}
              <span className="text-sm font-normal text-ink-muted">
                {unlimited ? " (no limit)" : ` of ${amount(limit, u.unit)}`}
              </span>
            </p>
            <ProgressBar
              value={percent}
              tone={blocking ? "danger" : unlimited ? "muted" : "accent"}
              label={`${u.label}: ${amount(u.used, u.unit)} of ${
                unlimited ? "unlimited" : amount(limit, u.unit)
              }`}
            />
            {note && (
              <p className={cn("text-xs", blocking ? "text-danger" : "text-ink-muted")}>{note}</p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function PortalButton({
  label,
  variant = "primary",
}: {
  label: string;
  variant?: "primary" | "secondary";
}) {
  const [busy, setBusy] = useState(false);
  const open = useCallback(async () => {
    setBusy(true);
    try {
      const { url } = await unwrap(api.POST("/api/billing/portal"));
      window.location.assign(url);
    } catch (err) {
      toast.error("Could not open billing.", { description: errorMessage(err) });
      setBusy(false);
    }
  }, []);
  return (
    <Button variant={variant} disabled={busy} onClick={() => void open()}>
      <ExternalLink aria-hidden="true" />
      {busy ? "Opening…" : label}
    </Button>
  );
}

function PlanPicker({
  overview,
  plans,
  wanted,
}: {
  overview: BillingOverview;
  plans: Plans | null;
  wanted: string | null;
}) {
  const [interval, setPeriod] = useState<BillingInterval>("month");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!plans) return <Skeleton className="h-48 w-full" />;
  const options = plans.plans.filter((p) => p.price_monthly > 0 || p.contact_sales);
  const yearlyExists = options.some((p) => p.price_yearly > 0);

  async function choose(plan: Plan) {
    setBusy(plan.id);
    setError(null);
    try {
      const { url } = await unwrap(
        api.POST("/api/billing/checkout", { body: { plan_id: plan.id, interval } }),
      );
      window.location.assign(url);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      {yearlyExists && (
        <fieldset className="inline-flex rounded-control border border-line-strong p-0.5">
          <legend className="sr-only">Billing period</legend>
          {(["month", "year"] as const).map((value) => (
            <label
              key={value}
              className={cn(
                "cursor-pointer rounded-[calc(var(--radius-control)-2px)] px-3 py-1.5 text-sm font-medium",
                "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent",
                interval === value ? "bg-accent text-accent-ink" : "text-ink-muted hover:text-ink",
              )}
            >
              <input
                type="radio"
                name="interval"
                value={value}
                checked={interval === value}
                onChange={() => setPeriod(value)}
                className="sr-only"
              />
              {value === "month" ? "Monthly" : "Yearly"}
            </label>
          ))}
        </fieldset>
      )}
      {error && <Alert tone="error">{error}</Alert>}
      <ul className="grid gap-4 md:grid-cols-2" aria-label="Plans">
        {options.map((plan) => {
          const cents = interval === "year" ? plan.price_yearly : plan.price_monthly;
          const trial = overview.trial_available && plan.trial_days > 0;
          const saved = interval === "year" ? monthsFree(plan) : 0;
          const highlight = wanted ? wanted === plan.id : plan.highlighted;
          return (
            <li
              key={plan.id}
              data-plan={plan.id}
              className={cn(
                "flex flex-col rounded-sheet border bg-surface p-5",
                highlight ? "border-accent ring-1 ring-accent" : "border-line",
              )}
            >
              <div className="flex items-center justify-between gap-3">
                <h3 className="font-semibold">{plan.name}</h3>
                {plan.highlighted && <Badge tone="accent">Recommended</Badge>}
              </div>
              <p className="mt-1 text-sm text-ink-muted">{plan.description}</p>
              {!plan.contact_sales && cents > 0 && (
                <p className="mt-4 flex items-baseline gap-1.5">
                  <span className="text-2xl font-semibold tracking-tight tabular">
                    {formatPrice(cents, plans.currency)}
                  </span>
                  <span className="text-sm text-ink-muted">
                    a {interval}
                    {saved > 0 ? ` (${saved} ${saved === 1 ? "month" : "months"} free)` : ""}
                  </span>
                </p>
              )}
              <ul className="mt-4 flex-1 space-y-2 text-sm">
                {plan.features.map((feature) => (
                  <li key={feature} className="flex gap-2">
                    <Check className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>
              {plan.contact_sales ? (
                <Button asChild variant="secondary" className="mt-5">
                  <a href={`mailto:${legal.company.email}`}>Contact us about {plan.name}</a>
                </Button>
              ) : cents > 0 ? (
                <Button
                  className="mt-5"
                  variant={highlight ? "primary" : "secondary"}
                  disabled={busy !== null}
                  onClick={() => void choose(plan)}
                >
                  {busy === plan.id
                    ? "Opening checkout…"
                    : trial
                      ? `Try ${plan.name} free for ${plan.trial_days} days`
                      : `Upgrade to ${plan.name}`}
                </Button>
              ) : (
                <p className="mt-5 text-sm text-ink-muted">Not available {interval}ly.</p>
              )}
            </li>
          );
        })}
      </ul>
      <p className="text-sm text-ink-muted">
        {plans.prices_include_vat
          ? "All prices include VAT."
          : "All prices plus VAT. Enter your VAT ID at checkout."}{" "}
        {overview.trial_available
          ? "A trial asks for a card but charges nothing until it ends; cancel before and you pay nothing."
          : ""}
      </p>
    </div>
  );
}
