import type { Metadata } from "next";

import { CallToAction } from "@/components/marketing/call-to-action";
import { FaqList } from "@/components/marketing/faq-list";
import { PlanComparison, PricingPlans } from "@/components/marketing/pricing";
import { marketing } from "@/config/marketing";
import { getPlans } from "@/lib/api/server";

export const metadata: Metadata = {
  title: "Pricing",
  description: marketing.pricing.intro,
};

/** Pricing page: plans from the backend (backend/app/core/plans.py), limits side by side, FAQ. */
export default async function PricingPage() {
  const plans = await getPlans();
  const { pricing, faq, cta } = marketing;
  return (
    <>
      <section className="mx-auto max-w-6xl px-4 pt-12 pb-20 sm:px-6 sm:pt-20">
        <h1 className="text-[clamp(2.2rem,5vw,3.5rem)] leading-[1.05] font-semibold tracking-[-0.03em]">
          {pricing.title}
        </h1>
        <p className="mt-4 mb-12 max-w-[52ch] text-lg text-ink-muted">{pricing.intro}</p>
        <PricingPlans plans={plans} headingLevel={2} />
      </section>

      <section aria-labelledby="compare-title" className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
        <h2 id="compare-title" className="mb-6 text-2xl font-semibold tracking-tight">
          Compare plans
        </h2>
        <PlanComparison plans={plans} />
      </section>

      <section
        aria-labelledby="faq-title"
        className="mx-auto grid max-w-6xl gap-10 px-4 pb-24 sm:px-6 lg:grid-cols-[minmax(0,20rem)_1fr] lg:gap-20"
      >
        <h2 id="faq-title" className="text-2xl font-semibold tracking-tight">
          {faq.title}
        </h2>
        <FaqList items={faq.items} />
      </section>

      <CallToAction title={cta.title} text={cta.text} action={cta.action} />
    </>
  );
}
