import { cn } from "@/lib/utils";

/** Placeholder block shown while content loads. */
export function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-control bg-surface-sunken", className)}
      {...props}
    />
  );
}
