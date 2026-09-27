import { TriangleAlert } from "lucide-react";

import { legal, legalHasPlaceholders } from "@/config/legal";

// A calendar date, not a moment in time: format in UTC so no time zone shifts it a day.
const updatedText = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "long",
  timeZone: "UTC",
}).format(new Date(`${legal.updated}T00:00:00Z`));

/** Shows a config value; any "[placeholder]" part is highlighted so it can't be missed. */
export function Value({ children }: { children: string }) {
  const parts = children.split(/(\[[^\]]+\])/g).filter(Boolean);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith("[") ? (
          <mark key={i} className="rounded-[3px] bg-warning/15 px-0.5 text-inherit">
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  );
}

/** The company block used on several legal pages. */
export function CompanyAddress() {
  const c = legal.company;
  return (
    <address className="not-italic">
      <Value>{c.name}</Value>
      <br />
      <Value>{c.street}</Value>
      <br />
      <Value>{`${c.postalCode} ${c.city}`}</Value>
      <br />
      <Value>{c.country}</Value>
    </address>
  );
}

/**
 * Frame for every legal page: title, date, and a warning box while the texts are still
 * unreviewed templates (config/legal.ts: `reviewed: false` or [placeholders] left).
 */
export function LegalPage({
  title,
  intro,
  children,
}: {
  title: string;
  intro?: string;
  children: React.ReactNode;
}) {
  const unfinished = !legal.reviewed || legalHasPlaceholders();
  return (
    <article className="mx-auto max-w-3xl px-4 pt-12 pb-24 sm:px-6 sm:pt-16">
      <h1 className="text-[clamp(2rem,5vw,2.75rem)] leading-tight font-semibold tracking-[-0.025em]">
        {title}
      </h1>
      <p className="mt-2 text-sm text-ink-muted">
        Last updated <time dateTime={legal.updated}>{updatedText}</time>
      </p>
      {unfinished && (
        <div
          role="note"
          aria-label="Template warning"
          className="mt-8 flex gap-3 rounded-menu border border-warning/40 bg-warning/10 p-4 text-sm"
        >
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
          <p>
            <strong className="font-semibold">Template, not legal advice.</strong> Fill in the
            highlighted parts in <code>config/legal.ts</code>, have the text checked by a lawyer,
            then set <code>reviewed: true</code>. See <code>docs/LEGAL_TEMPLATES.md</code>.
          </p>
        </div>
      )}
      {intro && <p className="mt-8 text-lg text-ink-muted">{intro}</p>}
      <div className="legal-prose mt-10">{children}</div>
    </article>
  );
}
