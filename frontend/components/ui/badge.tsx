import { cn } from "@/lib/utils";

const tones = {
  neutral: "border-line-strong text-ink-muted",
  accent: "border-accent/30 bg-accent-soft text-accent",
  success: "border-success/30 bg-success/5 text-success",
  warning: "border-warning/30 bg-warning/5 text-warning",
  danger: "border-danger/30 bg-danger/5 text-danger",
} as const;

/** Small label for a status or a role ("Owner", "Expired"). Text, not color alone. */
export function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: keyof typeof tones;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-full border px-2 text-xs font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
