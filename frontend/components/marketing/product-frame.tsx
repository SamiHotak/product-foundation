import type { DemoVideo } from "@/config/marketing";
import { product } from "@/config/product";

/**
 * The window under the hero headline. With a demo video in config/marketing.ts it plays the
 * video; without one it shows a small, drawn preview of the app (pure HTML + CSS, so it costs
 * no image download and always matches the product's colors and dark mode).
 */
export function ProductFrame({ video }: { video: DemoVideo | null }) {
  return (
    <div className="rounded-sheet border border-line-strong bg-surface p-1.5 shadow-[0_30px_60px_-30px_rgb(27_34_51/0.35)] dark:shadow-[0_30px_60px_-30px_rgb(0_0_0/0.7)]">
      <div className="flex items-center gap-1.5 px-2.5 pt-1 pb-2" aria-hidden="true">
        <span className="size-2.5 rounded-full bg-line-strong" />
        <span className="size-2.5 rounded-full bg-line-strong" />
        <span className="size-2.5 rounded-full bg-line-strong" />
      </div>
      {video ? <DemoVideoPlayer video={video} /> : <AppPreview />}
    </div>
  );
}

function DemoVideoPlayer({ video }: { video: DemoVideo }) {
  return (
    // preload="none": nothing is downloaded until the visitor presses play (fast page).
    <video
      controls
      preload="none"
      playsInline
      poster={video.poster}
      width={video.width}
      height={video.height}
      className="block h-auto w-full rounded-[10px] bg-canvas"
      aria-label={`Demo of ${product.name}`}
    >
      <source src={video.src} type="video/mp4" />
      {video.captions && (
        <track kind="captions" src={video.captions} srcLang="en" label="English" default />
      )}
    </video>
  );
}

const PREVIEW_JOBS = [
  { name: "Monthly report", status: "Running", progress: 64 },
  { name: "Import contacts", status: "Done", progress: 100 },
  { name: "Export workspace", status: "Done", progress: 100 },
  { name: "Weekly summary email", status: "Done", progress: 100 },
  { name: "Clean up old files", status: "Done", progress: 100 },
];

const PREVIEW_USAGE = [
  { label: "Jobs this month", used: 1284, limit: 2000 },
  { label: "People", used: 4, limit: 5 },
  { label: "API keys", used: 2, limit: 10 },
];

const PREVIEW_PEOPLE = [
  { name: "Lena Hoffmann", role: "Owner" },
  { name: "Omar Siddiqui", role: "Admin" },
  { name: "Julia Brandt", role: "Member" },
  { name: "Samir Nazari", role: "Member" },
];

/** A static picture of the app, built from the real design tokens. Decorative only. */
function AppPreview() {
  return (
    <div
      role="img"
      aria-label={`Preview of ${product.name}: a dashboard with background jobs and team members`}
      className="grid aspect-video grid-cols-[9.5rem_1fr] overflow-hidden rounded-[10px] bg-canvas text-left text-[11px] select-none max-sm:aspect-[4/5] max-sm:grid-cols-1 sm:text-[12px] lg:grid-cols-[12rem_1fr] lg:text-[14px]"
    >
      <div aria-hidden="true" className="space-y-1 border-r border-line p-3 max-sm:hidden lg:p-4">
        <div className="mb-4 flex items-center gap-2">
          <span className="grid size-5 place-items-center rounded-[5px] bg-accent text-[0.9em] font-bold text-accent-ink">
            {product.monogram}
          </span>
          <span className="text-[1.1em] font-semibold">{product.name}</span>
        </div>
        {["Dashboard", "Jobs", "Team", "Settings"].map((item, i) => (
          <div
            key={item}
            className={
              i === 0
                ? "rounded-[5px] bg-accent-soft px-2 py-1.5 text-[1em] font-medium text-accent"
                : "px-2 py-1.5 text-[1em] text-ink-muted"
            }
          >
            {item}
          </div>
        ))}
      </div>
      <div aria-hidden="true" className="flex min-w-0 flex-col gap-3 p-3 sm:p-4 lg:gap-5 lg:p-6">
        <div className="flex items-center justify-between">
          <span className="text-[1.3em] font-semibold">Dashboard</span>
          <span className="rounded-[5px] bg-accent px-2 py-1 text-[0.9em] font-medium text-accent-ink">
            New job
          </span>
        </div>
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:gap-5">
          {PREVIEW_USAGE.map((meter, i) => (
            <li
              key={meter.label}
              className={`rounded-[8px] border border-line bg-surface p-3 lg:p-4 ${i === 2 ? "max-sm:hidden" : ""}`}
            >
              <div className="text-[0.9em] text-ink-muted">{meter.label}</div>
              <div className="mt-1 text-[1.4em] font-semibold tabular">
                {meter.used.toLocaleString("en")}
                <span className="text-[0.65em] font-normal text-ink-muted">
                  {" "}
                  of {meter.limit.toLocaleString("en")}
                </span>
              </div>
              <div className="mt-2 h-1 overflow-hidden rounded-full bg-surface-sunken">
                <div
                  className="h-full rounded-full bg-accent/60"
                  style={{ width: `${Math.round((meter.used / meter.limit) * 100)}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
        <div className="grid min-h-0 flex-1 items-start gap-3 sm:grid-cols-[1.4fr_1fr] lg:gap-5">
          <div className="rounded-[8px] border border-line bg-surface p-3 lg:p-4">
            <div className="mb-2.5 text-[1em] font-semibold">Background jobs</div>
            <ul className="space-y-2.5">
              {PREVIEW_JOBS.map((job, i) => (
                <li key={job.name} className="space-y-1">
                  <div className="flex justify-between text-[1em]">
                    <span>{job.name}</span>
                    <span
                      className={job.status === "Done" ? "text-success" : "text-ink-muted tabular"}
                    >
                      {job.status === "Done" ? "Done" : `${job.progress}%`}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-surface-sunken">
                    <div
                      className={
                        i === 0
                          ? "preview-progress h-full rounded-full bg-accent"
                          : "h-full rounded-full bg-success/70"
                      }
                      style={{ width: `${job.progress}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-[8px] border border-line bg-surface p-3 lg:p-4">
            <div className="mb-2 text-[1em] font-semibold">Team</div>
            <ul className="divide-y divide-line">
              {PREVIEW_PEOPLE.map((person) => (
                <li key={person.name} className="flex items-center gap-2 py-1.5 text-[1em]">
                  <span className="grid size-5 place-items-center rounded-full bg-surface-sunken text-[0.8em] font-semibold text-ink-muted">
                    {person.name
                      .split(" ")
                      .map((part) => part[0])
                      .join("")}
                  </span>
                  <span className="flex-1 truncate">{person.name}</span>
                  <span className="rounded-full border border-line-strong px-1.5 text-[0.9em] text-ink-muted">
                    {person.role}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
