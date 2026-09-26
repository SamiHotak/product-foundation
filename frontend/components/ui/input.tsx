import * as React from "react";

import { cn } from "@/lib/utils";

/** Text input. Pair with <Field> for a label and an error message. */
export function Input({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "h-10 w-full rounded-control border border-line-strong bg-surface px-3 text-sm text-ink",
        "placeholder:text-ink-muted/70 focus-visible:border-accent focus-visible:outline-none",
        "focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
        "aria-[invalid=true]:border-danger",
        className,
      )}
      {...props}
    />
  );
}
