import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * Label + control + hint/error, wired for screen readers.
 * Render prop gives the control its id and aria attributes.
 */
export function Field({
  label,
  hint,
  error,
  action,
  className,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  /** Small link on the right of the label (e.g. "Forgot password?"). */
  action?: React.ReactNode;
  className?: string;
  children: (props: {
    id: string;
    "aria-invalid": boolean;
    "aria-describedby"?: string;
  }) => React.ReactNode;
}) {
  const id = useId();
  const noteId = `${id}-note`;
  const note = error ?? hint;
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        {action}
      </div>
      {children({ id, "aria-invalid": !!error, "aria-describedby": note ? noteId : undefined })}
      {note && (
        <p id={noteId} className={cn("text-xs", error ? "text-danger" : "text-ink-muted")}>
          {note}
        </p>
      )}
    </div>
  );
}
