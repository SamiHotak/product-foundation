import { Check } from "lucide-react";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { legal } from "@/config/legal";
import type { Plan, Plans } from "@/lib/api";
import { cn } from "@/lib/utils";

/** "€29", "€29.50" (no ".00"). */
export function formatPrice(cents: number, currency: string): string {
  return new Intl.NumberFormat("en-IE", {
    style: "currency",
    currency: currency.toUpperCase(),
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);
}

/** Whole months saved by paying yearly (0 if none). */
export function monthsFree(plan: Plan): number {
  if (plan.price_monthly <= 0 || plan.price_yearly <= 0) return 0;
  return Math.max(
    0,
    Math.round((plan.price_monthly * 12 - plan.price_yearly) / plan.price_monthly),
  );
}

function planAction(plan: Plan): { label: string; href: string } {
  if (plan.contact_sales) return { label: "Contact us", href: `mailto:${legal.company.email}` };
  if (plan.price_monthly === 0) return { label: "Start for free", href: "/signup" };
  if (plan.trial_days > 0) {
    return { label: `Start ${plan.trial_days}-day trial`, href: `/signup?plan=${plan.id}` };
  }
  return { label: `Choose ${plan.name}`, href: `/signup?plan=${plan.id}` };
}

/**
 * The plan columns. Data comes from the backend (`GET /api/billing/plans`), which reads
 * backend/app/core/plans.py, so prices here always match what checkout charges.
 */
export function PricingPlans({
  plans,
  headingLevel = 3,
}: {
  plans: Plans | null;
  /** Plan names are h3 under a section h2 (landing page), h2 right under the h1 (pricing page). */
  headingLevel?: 2 | 3;
}) {
  const PlanHeading = headingLevel === 2 ? "h2" : "h3";
  if (!plans || plans.plans.length === 0) {
    return (
      <Alert className="max-w-xl">
        Prices could not be loaded right now. Refresh the page in a minute.
      </Alert>
    );
  }
  const { currency } = plans;
  return (
    <div className="space-y-5">
      <ul
        className={cn(
          "grid gap-4",
          plans.plans.length >= 3 ? "lg:grid-cols-3" : "md:grid-cols-2",
          plans.plans.length === 2 && "max-w-3xl",
        )}
      >
        {plans.plans.map((plan) => {
          const action = planAction(plan);
          const saved = monthsFree(plan);
          return (
            <li
              key={plan.id}
              data-plan={plan.id}
              className={cn(
                "flex flex-col rounded-sheet border bg-surface p-6",
                plan.highlighted ? "border-accent ring-1 ring-accent" : "border-line",
              )}
            >
              <div className="flex items-center justify-between gap-3">
                <PlanHeading className="text-lg font-semibold">{plan.name}</PlanHeading>
                {plan.highlighted && <Badge tone="accent">Recommended</Badge>}
              </div>
              <p className="mt-1 text-sm text-ink-muted">{plan.description}</p>
              <p className="mt-6 flex items-baseline gap-1.5">
                <span className="text-4xl font-semibold tracking-tight tabular">
                  {formatPrice(plan.price_monthly, currency)}
                </span>
                <span className="text-sm text-ink-muted">a month</span>
              </p>
              <p className="mt-1 min-h-5 text-sm text-ink-muted">
                {plan.price_yearly > 0 &&
                  `or ${formatPrice(plan.price_yearly, currency)} a year${
                    saved > 0 ? ` (${saved} ${saved === 1 ? "month" : "months"} free)` : ""
                  }`}
              </p>
              <Button
                asChild
                variant={plan.highlighted ? "primary" : "secondary"}
                className="mt-6 h-10"
              >
                <Link href={action.href}>{action.label}</Link>
              </Button>
              <ul className="mt-6 space-y-2.5 text-sm">
                {plan.features.map((feature) => (
                  <li key={feature} className="flex gap-2.5">
                    <Check className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
      <p className="text-sm text-ink-muted">
        {plans.prices_include_vat
          ? "All prices include VAT."
          : "All prices plus VAT. For business customers."}
      </p>
    </div>
  );
}

function limitText(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Unlimited";
  return value.toLocaleString("en");
}

/** Side-by-side limits of every plan (pricing page). Scrolls sideways on small phones. */
export function PlanComparison({ plans }: { plans: Plans | null }) {
  if (!plans || plans.plans.length === 0) return null;
  const rows: { label: string; value: (plan: Plan) => string }[] = [
    { label: "People in a workspace", value: (p) => limitText(p.limits.members) },
    { label: "Background jobs a month", value: (p) => limitText(p.limits.jobs_per_month) },
    { label: "API keys", value: (p) => limitText(p.limits.api_keys) },
    { label: "Free trial", value: (p) => (p.trial_days > 0 ? `${p.trial_days} days` : "None") },
  ];
  return (
    <div className="overflow-x-auto rounded-sheet border border-line bg-surface">
      <table className="w-full min-w-[32rem] text-sm">
        <caption className="sr-only">What each plan includes</caption>
        <thead>
          <tr className="border-b border-line">
            <th scope="col" className="w-2/5 px-5 py-3.5 text-left font-medium text-ink-muted">
              Included
            </th>
            {plans.plans.map((plan) => (
              <th key={plan.id} scope="col" className="px-5 py-3.5 text-left font-semibold">
                {plan.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row) => (
            <tr key={row.label}>
              <th scope="row" className="px-5 py-3.5 text-left font-normal text-ink-muted">
                {row.label}
              </th>
              {plans.plans.map((plan) => (
                <td key={plan.id} className="px-5 py-3.5 tabular">
                  {row.value(plan)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
