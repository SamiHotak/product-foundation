import Link from "next/link";

import { CallToAction } from "@/components/marketing/call-to-action";
import { FaqList } from "@/components/marketing/faq-list";
import { PricingPlans } from "@/components/marketing/pricing";
import { ProductFrame } from "@/components/marketing/product-frame";
import { Button } from "@/components/ui/button";
import { marketing } from "@/config/marketing";
import { getPlans } from "@/lib/api/server";

/**
 * Landing page. All text comes from config/marketing.ts, the plans from the backend.
 * Sections: hero (with demo video slot), features, how it works, pricing, FAQ, call to action.
 */
export default async function LandingPage() {
  const plans = await getPlans();
  const { hero, features, steps, pricing, faq, cta } = marketing;

  return (
    <>
      <section className="mx-auto max-w-6xl px-4 pt-12 sm:px-6 sm:pt-20">
        <h1 className="max-w-[18ch] text-[clamp(2.4rem,6vw,4.25rem)] leading-[1.02] font-semibold tracking-[-0.035em] text-balance">
          {hero.title}
        </h1>
        <p className="mt-6 max-w-[52ch] text-lg text-pretty text-ink-muted">{hero.subtitle}</p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Button asChild className="h-11 px-5 text-[15px]">
            <Link href={hero.primary.href}>{hero.primary.label}</Link>
          </Button>
          <Button asChild variant="secondary" className="h-11 px-5 text-[15px]">
            <Link href={hero.secondary.href}>{hero.secondary.label}</Link>
          </Button>
        </div>
        <div className="mt-14 sm:mt-20 lg:-mx-6">
          <ProductFrame video={hero.video} />
        </div>
      </section>

      <section
        id="features"
        aria-labelledby="features-title"
        className="mx-auto grid max-w-6xl scroll-mt-6 gap-10 px-4 py-24 sm:px-6 sm:py-32 lg:grid-cols-[minmax(0,20rem)_1fr] lg:gap-20"
      >
        <div className="lg:sticky lg:top-10 lg:self-start">
          <h2 id="features-title" className="text-3xl font-semibold tracking-tight">
            {features.title}
          </h2>
          <p className="mt-3 text-ink-muted">{features.intro}</p>
        </div>
        <ul className="grid gap-x-10 gap-y-10 sm:grid-cols-2">
          {features.items.map(({ icon: Icon, title, text }) => (
            <li key={title}>
              <Icon className="size-5 text-accent" aria-hidden="true" />
              <h3 className="mt-3 font-semibold">{title}</h3>
              <p className="mt-1.5 text-ink-muted">{text}</p>
            </li>
          ))}
        </ul>
      </section>

      <section
        id="how-it-works"
        aria-labelledby="steps-title"
        className="scroll-mt-6 border-y border-line bg-surface"
      >
        <div className="mx-auto max-w-6xl px-4 py-24 sm:px-6 sm:py-28">
          <h2 id="steps-title" className="text-3xl font-semibold tracking-tight">
            {steps.title}
          </h2>
          <ol className="mt-12 grid gap-10 md:grid-cols-3 md:gap-8">
            {steps.items.map((step, i) => (
              <li key={step.title}>
                <div className="flex items-center gap-4">
                  <span className="grid size-9 shrink-0 place-items-center rounded-full border border-accent/40 bg-accent-soft font-semibold text-accent tabular">
                    {i + 1}
                  </span>
                  {i < steps.items.length - 1 && (
                    <span
                      aria-hidden="true"
                      className="hidden h-px flex-1 bg-line-strong md:block"
                    />
                  )}
                </div>
                <h3 className="mt-5 text-lg font-semibold">{step.title}</h3>
                <p className="mt-1.5 max-w-[34ch] text-ink-muted">{step.text}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section
        id="pricing"
        aria-labelledby="pricing-title"
        className="mx-auto max-w-6xl scroll-mt-6 px-4 py-24 sm:px-6 sm:py-32"
      >
        <div className="mb-12 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="pricing-title" className="text-3xl font-semibold tracking-tight">
              {pricing.title}
            </h2>
            <p className="mt-3 max-w-[52ch] text-ink-muted">{pricing.intro}</p>
          </div>
          <Link href="/pricing" className="text-sm font-medium text-accent hover:underline">
            Compare all plans
          </Link>
        </div>
        <PricingPlans plans={plans} />
      </section>

      <section
        id="faq"
        aria-labelledby="faq-title"
        className="mx-auto grid max-w-6xl scroll-mt-6 gap-10 px-4 pb-24 sm:px-6 sm:pb-32 lg:grid-cols-[minmax(0,20rem)_1fr] lg:gap-20"
      >
        <h2 id="faq-title" className="text-3xl font-semibold tracking-tight">
          {faq.title}
        </h2>
        <FaqList items={faq.items} />
      </section>

      <CallToAction title={cta.title} text={cta.text} action={cta.action} />
    </>
  );
}
