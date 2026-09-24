import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

type EmptyStateProps = {
  icon: LucideIcon;
  title: string;
  description: string;
  /** The one clear next step (usually a Button). */
  action?: React.ReactNode;
  className?: string;
};

/** Shown when a page or list has nothing yet. Always say what to do next. */
export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-start gap-3 rounded-menu border border-dashed border-line-strong p-8",
        className,
      )}
    >
      <Icon className="size-6 text-ink-muted" aria-hidden="true" />
      <div className="space-y-1">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="max-w-prose text-sm text-ink-muted">{description}</p>
      </div>
      {action}
    </div>
  );
}
