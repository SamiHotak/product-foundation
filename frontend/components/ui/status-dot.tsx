import { cn } from "@/lib/utils";

type Tone = "ok" | "error" | "pending" | "active";

const tones: Record<Tone, string> = {
  ok: "bg-success",
  error: "bg-danger",
  pending: "bg-line-strong",
  // Something is happening right now: accent color with a soft pulse.
  active: "bg-accent animate-pulse",
};

/** Small colored dot. Always pair it with a text label (color alone is not accessible). */
export function StatusDot({ tone, className }: { tone: Tone; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("inline-block size-2 shrink-0 rounded-full", tones[tone], className)}
    />
  );
}
