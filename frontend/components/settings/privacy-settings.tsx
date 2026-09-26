"use client";

import { Download, FileArchive } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { JobProgress } from "@/components/jobs/job-progress";
import { useSession } from "@/components/session-provider";
import { Section } from "@/components/settings/section";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useApiData } from "@/hooks/use-api-data";
import { useJob } from "@/hooks/use-jobs";
import { api, errorMessage, unwrap, type DataExport } from "@/lib/api";
import { formatBytes, formatDate } from "@/lib/format";

/** Settings → Privacy: download your data, delete your account or the workspace (GDPR). */
export function PrivacySettings() {
  const { can } = useSession();
  const exports = useApiData(async () => (await unwrap(api.GET("/api/exports"))).items);
  const add = (item: DataExport) =>
    exports.setData((prev) => [item, ...(prev ?? []).filter((e) => e.id !== item.id)]);

  return (
    <div className="space-y-12">
      <ExportBlock
        scope="account"
        title="Download your data"
        description="A ZIP with everything we store about you: profile, workspaces, sign-ins and your activity. It takes a few seconds."
        buttonLabel="Export my data"
        start={() => unwrap(api.POST("/api/account/exports"))}
        items={exports.data}
        onStarted={add}
      />
      {can("org:export") && (
        <ExportBlock
          scope="organization"
          title="Download workspace data"
          description="A ZIP with all data of this workspace: members, invites, API keys (without secrets), the audit log and jobs."
          buttonLabel="Export workspace data"
          start={() => unwrap(api.POST("/api/organizations/current/exports"))}
          items={exports.data}
          onStarted={add}
        />
      )}
      {exports.error && <Alert tone="error">Could not load your exports: {exports.error}</Alert>}
      <DeleteAccount />
      {can("org:delete") && <DeleteWorkspace />}
    </div>
  );
}

// --- exports --------------------------------------------------------------------------------

function ExportBlock({
  scope,
  title,
  description,
  buttonLabel,
  start,
  items,
  onStarted,
}: {
  scope: DataExport["scope"];
  title: string;
  description: string;
  buttonLabel: string;
  start: () => Promise<DataExport>;
  items: DataExport[] | null;
  onStarted: (item: DataExport) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mine = (items ?? []).filter((e) => e.scope === scope);

  async function onClick() {
    setBusy(true);
    setError(null);
    try {
      onStarted(await start());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      title={title}
      description={description}
      actions={
        <Button variant="secondary" onClick={() => void onClick()} disabled={busy}>
          <FileArchive aria-hidden="true" />
          {busy ? "Starting…" : buttonLabel}
        </Button>
      }
    >
      {error && <Alert tone="error">{error}</Alert>}
      {mine.length > 0 && (
        <ul className="divide-y divide-line rounded-menu border border-line" aria-label={title}>
          {mine.map((item) => (
            <ExportRow key={item.id} item={item} />
          ))}
        </ul>
      )}
    </Section>
  );
}

/** One export: live progress while the worker builds it, then a download link. */
function ExportRow({ item }: { item: DataExport }) {
  const { job } = useJob(item.ready ? null : item.job_id);
  const ready = item.ready || job?.status === "done";
  const size = item.size_bytes ?? (job?.result?.size_bytes as number | undefined) ?? null;
  return (
    <li className="px-4 py-3" data-export-id={item.id}>
      {ready ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{item.filename}</p>
            <p className="text-xs text-ink-muted">
              {size !== null && `${formatBytes(size)}, `}available until{" "}
              {formatDate(item.expires_at)}
            </p>
          </div>
          <Button asChild variant="ghost" size="sm">
            <a href={item.download_url} download={item.filename}>
              <Download aria-hidden="true" />
              Download
            </a>
          </Button>
        </div>
      ) : job ? (
        <JobProgress job={job} />
      ) : (
        <p className="text-sm text-ink-muted">Preparing {item.filename}…</p>
      )}
    </li>
  );
}

// --- deletion -------------------------------------------------------------------------------

function DeleteAccount() {
  const router = useRouter();
  const { user } = useSession();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function keep() {
    setError(null);
    try {
      await unwrap(api.DELETE("/api/account/deletion"));
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Section
      title="Delete your account"
      description="Your profile, sign-ins and personal activity are deleted. Workspaces where you are the only person are deleted with it."
    >
      {error && <Alert tone="error">{error}</Alert>}
      {user.deletion_scheduled_at ? (
        <div className="flex flex-wrap items-center gap-3 rounded-menu border border-danger/30 bg-danger/5 p-4">
          <p className="min-w-0 flex-1 text-sm">
            Your account will be deleted on{" "}
            <strong>{formatDate(user.deletion_scheduled_at)}</strong>. Until then you can keep it.
          </p>
          <Button variant="secondary" onClick={() => void keep()}>
            Keep my account
          </Button>
        </div>
      ) : (
        <div>
          <Button variant="danger-outline" onClick={() => setOpen(true)}>
            Delete my account
          </Button>
        </div>
      )}
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Delete your account?"
        description="Nothing is deleted right away. You have time to change your mind, and we email you the exact date."
        confirmLabel="Delete my account"
        busyLabel="Scheduling…"
        typeToConfirm={user.email}
        typeLabel={`Type your email (${user.email}) to confirm`}
        onConfirm={async (typed) => {
          await unwrap(api.POST("/api/account/deletion", { body: { confirm: typed } }));
          router.refresh();
        }}
      />
    </Section>
  );
}

function DeleteWorkspace() {
  const router = useRouter();
  const { activeOrganization } = useSession();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function keep() {
    setError(null);
    try {
      await unwrap(api.DELETE("/api/organizations/current/deletion"));
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Section
      title="Delete this workspace"
      description={`“${activeOrganization.name}” and all its data are deleted for everyone in it. Their accounts stay.`}
    >
      {error && <Alert tone="error">{error}</Alert>}
      {activeOrganization.deletion_scheduled_at ? (
        <div className="flex flex-wrap items-center gap-3 rounded-menu border border-danger/30 bg-danger/5 p-4">
          <p className="min-w-0 flex-1 text-sm">
            This workspace will be deleted on{" "}
            <strong>{formatDate(activeOrganization.deletion_scheduled_at)}</strong>.
          </p>
          <Button variant="secondary" onClick={() => void keep()}>
            Keep the workspace
          </Button>
        </div>
      ) : (
        <div>
          <Button variant="danger-outline" onClick={() => setOpen(true)}>
            Delete workspace
          </Button>
        </div>
      )}
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Delete “${activeOrganization.name}”?`}
        description="Nothing is deleted right away. You have time to change your mind, and we email you the exact date. Download the workspace data first if you need a copy."
        confirmLabel="Delete workspace"
        busyLabel="Scheduling…"
        typeToConfirm={activeOrganization.name}
        typeLabel="Type the workspace name to confirm"
        onConfirm={async (typed) => {
          await unwrap(
            api.POST("/api/organizations/current/deletion", { body: { confirm: typed } }),
          );
          router.refresh();
        }}
      />
    </Section>
  );
}
