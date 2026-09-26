import { CircleCheck, Info, TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";

const tones = {
  error: { icon: TriangleAlert, className: "border-danger/30 bg-danger/5 text-danger" },
  success: { icon: CircleCheck, className: "border-success/30 bg-success/5 text-success" },
  info: { icon: Info, className: "border-line-strong bg-surface-sunken text-ink" },
} as const;

/** Inline message box. Errors use role="alert" so screen readers announce them. */
export function Alert({
  tone = "info",
  children,
  className,
}: {
  tone?: keyof typeof tones;
  children: React.ReactNode;
  className?: string;
}) {
  const { icon: Icon, className: toneClass } = tones[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex gap-2.5 rounded-control border px-3 py-2.5 text-sm",
        toneClass,
        className,
      )}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 space-y-2 [&_*]:text-inherit">{children}</div>
    </div>
  );
}
