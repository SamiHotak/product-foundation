import { cn } from "@/lib/utils";

type Tone = "accent" | "success" | "danger" | "muted";

const fills: Record<Tone, string> = {
  accent: "bg-accent",
  success: "bg-success",
  danger: "bg-danger",
  muted: "bg-line-strong",
};

/** Thin horizontal progress bar (0-100). `label` is read by screen readers. */
export function ProgressBar({
  value,
  label,
  tone = "accent",
  className,
}: {
  value: number;
  label: string;
  tone?: Tone;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken", className)}
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-500 ease-out", fills[tone])}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
