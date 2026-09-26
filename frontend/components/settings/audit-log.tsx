"use client";

import { History } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/session-provider";
import { NoAccess } from "@/components/settings/section";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api, errorMessage, unwrap, type AuditEntry } from "@/lib/api";
import { formatDate, formatTime } from "@/lib/format";

const FILTERS = [
  { value: "", label: "All activity" },
  { value: "member", label: "Team changes" },
  { value: "invite", label: "Invites" },
  { value: "api_key", label: "API keys" },
  { value: "org", label: "Workspace settings" },
] as const;

type Details = Record<string, unknown>;

function text(details: Details, key: string): string {
  const value = details[key];
  return typeof value === "string" ? value : "";
}

/** One readable sentence per event. Products add their own actions here. */
function describe(entry: AuditEntry): string {
  const d = entry.details as Details;
  switch (entry.action) {
    case "org.created":
      return `created the workspace “${text(d, "name")}”`;
    case "org.renamed":
      return `renamed the workspace from “${text(d, "from")}” to “${text(d, "to")}”`;
    case "org.ownership_transferred":
      return text(d, "to")
        ? `made ${text(d, "to")} the owner`
        : `handed ownership to the next admin. ${text(d, "reason")}`;
    case "org.exported":
      return "exported all workspace data";
    case "org.deletion_scheduled":
      return `scheduled this workspace to be deleted on ${formatDate(text(d, "deletion_scheduled_at"))}`;
    case "org.deletion_cancelled":
      return "cancelled deleting this workspace";
    case "invite.created":
      return `invited ${text(d, "email")} as ${text(d, "role")}`;
    case "invite.resent":
      return `sent the invite to ${text(d, "email")} again`;
    case "invite.revoked":
      return `cancelled the invite to ${text(d, "email")}`;
    case "member.joined":
      return `joined as ${text(d, "role")}`;
    case "member.role_changed":
      return `changed the role of ${text(d, "email")} from ${text(d, "from")} to ${text(d, "to")}`;
    case "member.removed":
      return `removed ${text(d, "email")} from the workspace`;
    case "member.left":
      return "left the workspace";
    case "api_key.created":
      return `created the API key “${text(d, "name")}”`;
    case "api_key.revoked":
      return `revoked the API key “${text(d, "name")}”`;
    default:
      return entry.action;
  }
}

function actorName(entry: AuditEntry): string {
  switch (entry.actor.type) {
    case "user":
    case "api_key":
      return entry.actor.name ?? "Someone";
    case "system":
      return "The system";
    default:
      return "A deleted user";
  }
}

function dayLabel(iso: string): string {
  const day = new Date(iso).toDateString();
  const today = new Date();
  if (day === today.toDateString()) return "Today";
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (day === yesterday.toDateString()) return "Yesterday";
  return formatDate(iso);
}

function byDay(entries: AuditEntry[]): [string, AuditEntry[]][] {
  const groups = new Map<string, AuditEntry[]>();
  for (const entry of entries) {
    const label = dayLabel(entry.created_at);
    groups.set(label, [...(groups.get(label) ?? []), entry]);
  }
  return [...groups.entries()];
}

/** Settings → Audit log: who did what, newest first. */
export function AuditLog() {
  const { can } = useSession();
  const allowed = can("audit:read");
  const [filter, setFilter] = useState("");
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const load = useCallback(
    async (before: string | null) => {
      const query: { limit: number; before?: string; action?: string } = { limit: 50 };
      if (before) query.before = before;
      if (filter) query.action = filter;
      return unwrap(api.GET("/api/organizations/current/audit-log", { params: { query } }));
    },
    [filter],
  );

  useEffect(() => {
    if (!allowed) return;
    let cancelled = false;
    // Data fetching from an external system: first page for the chosen filter.
    load(null)
      .then((page) => {
        if (cancelled) return;
        setEntries(page.items);
        setCursor(page.next_cursor);
        setError(null);
      })
      .catch((err: unknown) => !cancelled && setError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, [allowed, load]);

  async function more() {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const page = await load(cursor);
      setEntries((prev) => [...(prev ?? []), ...page.items]);
      setCursor(page.next_cursor);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoadingMore(false);
    }
  }

  if (!allowed) {
    return <NoAccess>Only owners and admins can see the audit log.</NoAccess>;
  }
  return (
    <section aria-labelledby="audit-title" className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-0.5">
          <h2 id="audit-title" className="text-base font-semibold">
            Audit log
          </h2>
          <p className="max-w-prose text-sm text-ink-muted">
            Every change to the team, invites, API keys and workspace settings. Kept for one year.
          </p>
        </div>
        <Select
          aria-label="Show"
          className="w-48"
          value={filter}
          onChange={(e) => {
            setEntries(null);
            setFilter(e.target.value);
          }}
        >
          {FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </Select>
      </div>

      {error && <Alert tone="error">Could not load the audit log: {error}</Alert>}

      {entries === null && !error && (
        <div className="space-y-2" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      )}

      {entries !== null && entries.length === 0 && (
        <EmptyState
          icon={History}
          title="Nothing here yet"
          description="Events appear here as soon as someone changes the team, invites or keys."
        />
      )}

      {entries !== null &&
        byDay(entries).map(([day, items]) => (
          <div key={day} className="space-y-1.5">
            <h3 className="text-sm font-medium text-ink-muted">{day}</h3>
            <ol className="divide-y divide-line rounded-menu border border-line">
              {items.map((entry) => (
                <li
                  key={entry.id}
                  className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 px-4 py-2.5 text-sm"
                  data-action={entry.action}
                >
                  <p className="min-w-0 flex-1">
                    <span className="font-medium">{actorName(entry)}</span> {describe(entry)}
                  </p>
                  <p className="text-xs text-ink-muted tabular">
                    {formatTime(entry.created_at)}
                    {entry.ip_address && <span className="ml-2">from {entry.ip_address}</span>}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        ))}

      {cursor && (
        <Button variant="secondary" onClick={() => void more()} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Show older events"}
        </Button>
      )}
    </section>
  );
}
