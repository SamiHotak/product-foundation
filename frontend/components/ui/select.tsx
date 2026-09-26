import { ChevronDown } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Native select, styled like Input. Native = right keyboard and screen-reader behaviour,
 * and the phone's own picker on mobile. Pair with <Field> or give it an aria-label.
 */
export function Select({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <div className={cn("relative", className)}>
      <select
        className={cn(
          "h-10 w-full appearance-none rounded-control border border-line-strong bg-surface pr-9 pl-3 text-sm text-ink",
          "focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
          "disabled:opacity-60",
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-ink-muted"
      />
    </div>
  );
}
