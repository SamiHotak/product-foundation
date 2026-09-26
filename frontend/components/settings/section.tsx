/** One block on a settings page: a heading, one line about it, then the content. */
export function Section({
  title,
  description,
  actions,
  children,
  id,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  id?: string;
}) {
  const headingId = id ?? `section-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section aria-labelledby={headingId} className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-0.5">
          <h2 id={headingId} className="text-base font-semibold">
            {title}
          </h2>
          {description && <p className="max-w-prose text-sm text-ink-muted">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** A quiet box for "you can't use this page" and similar notes. */
export function NoAccess({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-menu border border-dashed border-line-strong p-6 text-sm text-ink-muted">
      {children}
    </p>
  );
}
