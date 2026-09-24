/** Page title + one line that says what the page is for. */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="space-y-1.5">
        <h1 className="text-display font-semibold">{title}</h1>
        {description && <p className="max-w-prose text-ink-muted">{description}</p>}
      </div>
      {actions}
    </div>
  );
}
