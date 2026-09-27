import Link from "next/link";

/** The closing band on the landing and pricing pages: one sentence and one action. */
export function CallToAction({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action: { label: string; href: string };
}) {
  return (
    <section aria-labelledby="cta-title" className="px-4 pb-24 sm:px-6">
      <div className="mx-auto flex max-w-6xl flex-col items-start gap-6 rounded-sheet bg-accent px-6 py-12 text-accent-ink sm:px-12 sm:py-16 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 id="cta-title" className="text-3xl font-semibold tracking-tight">
            {title}
          </h2>
          <p className="mt-2 opacity-90">{text}</p>
        </div>
        <Link
          href={action.href}
          className="inline-flex h-11 shrink-0 items-center rounded-control bg-surface px-5 text-[15px] font-medium text-ink transition-colors hover:bg-surface-sunken"
        >
          {action.label}
        </Link>
      </div>
    </section>
  );
}
