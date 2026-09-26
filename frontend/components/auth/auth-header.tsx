/** Title + one line under it, same on every auth page. */
export function AuthHeader({
  title,
  description,
}: {
  title: string;
  description?: React.ReactNode;
}) {
  return (
    <div className="mb-6 space-y-1.5">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {description && <p className="text-sm text-ink-muted">{description}</p>}
    </div>
  );
}
