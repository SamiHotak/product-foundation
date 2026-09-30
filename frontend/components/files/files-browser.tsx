"use client";

import {
  Download,
  File as FileIcon,
  FileImage,
  FileSpreadsheet,
  FileText,
  FolderOpen,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiErrorAlert } from "@/components/billing/api-error-alert";
import { useSession } from "@/components/session-provider";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { ProgressBar } from "@/components/ui/progress-bar";
import { toast } from "@/components/ui/toast";
import { useApiData } from "@/hooks/use-api-data";
import { useDataTable, type Column } from "@/hooks/use-data-table";
import { api, ApiError, errorMessage, unwrap, type StoredFile } from "@/lib/api";
import { formatBytes, formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

type UploadState = {
  id: string;
  name: string;
  size: number;
  progress: number;
  phase: "uploading" | "checking" | "done" | "error";
  error?: string;
  cause?: unknown;
};

function iconFor(contentType: string) {
  if (contentType.startsWith("image/")) return FileImage;
  if (contentType.includes("spreadsheet") || contentType === "text/csv") return FileSpreadsheet;
  if (
    contentType.startsWith("text/") ||
    contentType.includes("pdf") ||
    contentType.includes("word")
  )
    return FileText;
  return FileIcon;
}

/**
 * Send the file straight to the storage with the signed form from the API (it never
 * passes through our backend). XMLHttpRequest, because fetch() can't report progress.
 */
function sendToStorage(
  url: string,
  fields: Record<string, string>,
  file: File,
  onProgress: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const [key, value] of Object.entries(fields)) form.append(key, value);
    form.append("file", file); // must be the last field
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress((event.loaded / event.total) * 100);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else if (xhr.responseText.includes("EntityTooLarge"))
        reject(new Error("The file is bigger than it was when you chose it. Try again."));
      else reject(new Error(`The storage refused the upload (${xhr.status}). Try again.`));
    };
    xhr.onerror = () => reject(new Error("The upload was interrupted. Check your connection."));
    xhr.send(form);
  });
}

/** Files → upload (button or drag and drop), list, download and delete. */
export function FilesBrowser() {
  const { can, user } = useSession();
  const files = useApiData(() => unwrap(api.GET("/api/files")));
  const [uploads, setUploads] = useState<UploadState[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const reload = files.reload;

  // While a virus scan runs, check again every 2 seconds.
  const scanning = files.data?.items.some((f) => f.status === "scanning") ?? false;
  useEffect(() => {
    if (!scanning) return;
    const timer = setInterval(() => void reload(), 2000);
    return () => clearInterval(timer);
  }, [scanning, reload]);

  const update = useCallback((id: string, change: Partial<UploadState>) => {
    setUploads((prev) => prev.map((u) => (u.id === id ? { ...u, ...change } : u)));
  }, []);

  const uploadOne = useCallback(
    async (file: File) => {
      const id = `${Date.now()}-${Math.random()}`;
      setUploads((prev) => [
        { id, name: file.name, size: file.size, progress: 0, phase: "uploading" },
        ...prev,
      ]);
      try {
        const started = await unwrap(
          api.POST("/api/files/uploads", { body: { filename: file.name, size_bytes: file.size } }),
        );
        await sendToStorage(started.upload.url, started.upload.fields, file, (progress) =>
          update(id, { progress }),
        );
        update(id, { phase: "checking", progress: 100 });
        const done = await unwrap(
          api.POST("/api/files/{file_id}/complete", {
            params: { path: { file_id: started.file.id } },
          }),
        );
        update(id, { phase: "done" });
        toast.success(
          done.file.status === "scanning"
            ? `“${done.file.filename}” uploaded. Checking it for viruses…`
            : `“${done.file.filename}” uploaded.`,
        );
        setTimeout(() => setUploads((prev) => prev.filter((u) => u.id !== id)), 1500);
        void reload();
      } catch (err) {
        // A failed storage upload leaves an unfinished row: the nightly clean-up removes it.
        const message =
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : errorMessage(err);
        update(id, { phase: "error", error: message, cause: err });
      }
    },
    [reload, update],
  );

  function uploadAll(list: FileList | null) {
    if (!list) return;
    for (const file of Array.from(list)) void uploadOne(file);
    if (inputRef.current) inputRef.current.value = "";
  }

  const info = files.data;
  const canUpload = can("files:write") && !user.is_demo && info?.enabled !== false;
  const accept = info?.allowed_extensions.map((e) => `.${e}`).join(",");

  if (info === null && files.error)
    return <Alert tone="error">Could not load the files: {files.error}</Alert>;

  return (
    <div className="space-y-8">
      {info?.enabled === false && (
        <Alert>
          File uploads are not set up on this server yet (S3_ENDPOINT is empty). See
          docs/FILES_AND_AI.md.
        </Alert>
      )}
      {user.is_demo && (
        <Alert>This is the shared demo: you can download the sample files, not upload.</Alert>
      )}

      {canUpload && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            uploadAll(e.dataTransfer.files);
          }}
          className={cn(
            "flex flex-col items-start gap-3 rounded-menu border border-dashed p-6 transition-colors sm:flex-row sm:items-center",
            dragging ? "border-accent bg-accent-soft" : "border-line-strong",
          )}
        >
          <Upload className="size-5 text-ink-muted" aria-hidden="true" />
          <div className="min-w-0 flex-1 space-y-0.5">
            <p className="text-sm font-medium">Drop files here, or choose them</p>
            <p className="text-xs text-ink-muted">
              Up to {formatBytes(info?.max_bytes ?? 0)} each.{" "}
              {info && `Allowed: ${info.allowed_extensions.join(", ")}.`}
            </p>
          </div>
          <input
            ref={inputRef}
            id="file-input"
            type="file"
            multiple
            accept={accept}
            className="sr-only"
            onChange={(e) => uploadAll(e.target.files)}
          />
          <Button asChild variant="secondary">
            <label htmlFor="file-input" className="cursor-pointer">
              <Upload aria-hidden="true" />
              Choose files
            </label>
          </Button>
        </div>
      )}

      {uploads.length > 0 && (
        <ul className="space-y-3" aria-label="Uploads">
          {uploads.map((u) => (
            <li
              key={u.id}
              data-upload={u.name}
              data-phase={u.phase}
              className="space-y-2 rounded-menu border border-line p-3"
            >
              <div className="flex items-center gap-3 text-sm">
                <span className="min-w-0 flex-1 truncate font-medium">{u.name}</span>
                <span className="text-ink-muted tabular">{formatBytes(u.size)}</span>
                {u.phase === "error" && (
                  <button
                    type="button"
                    aria-label={`Hide the error for ${u.name}`}
                    className="grid size-6 place-items-center rounded-control text-ink-muted hover:bg-surface-sunken hover:text-ink"
                    onClick={() => setUploads((prev) => prev.filter((x) => x.id !== u.id))}
                  >
                    <X className="size-4" />
                  </button>
                )}
              </div>
              {u.phase === "error" ? (
                <ApiErrorAlert message={u.error ?? "Upload failed."} cause={u.cause} />
              ) : (
                <>
                  <ProgressBar
                    value={u.progress}
                    tone={u.phase === "done" ? "success" : "accent"}
                    label={`Uploading ${u.name}`}
                  />
                  <p className="text-xs text-ink-muted">
                    {u.phase === "uploading"
                      ? `Uploading… ${Math.round(u.progress)}%`
                      : u.phase === "checking"
                        ? "Checking the file…"
                        : "Done"}
                  </p>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      <FileTable
        files={info?.items ?? null}
        canUpload={canUpload}
        onChange={() => void reload()}
        onChoose={() => inputRef.current?.click()}
      />
    </div>
  );
}

function FileTable({
  files,
  canUpload,
  onChange,
  onChoose,
}: {
  files: StoredFile[] | null;
  canUpload: boolean;
  onChange: () => void;
  onChoose: () => void;
}) {
  const [deleting, setDeleting] = useState<StoredFile | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  async function download(file: StoredFile) {
    setDownloading(file.id);
    try {
      const link = await unwrap(
        api.POST("/api/files/{file_id}/download", { params: { path: { file_id: file.id } } }),
      );
      window.location.assign(link.url); // the storage sends it as a download
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setDownloading(null);
    }
  }

  const columns: Column<StoredFile>[] = [
    {
      id: "name",
      header: "Name",
      hideLabelOnPhone: true,
      sortValue: (f) => f.filename,
      cell: (f) => {
        const Icon = iconFor(f.content_type);
        return (
          <div className="flex min-w-0 items-center gap-3">
            <Icon className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
            <span className="truncate font-medium">{f.filename}</span>
            {f.status === "scanning" && <Badge tone="warning">Checking</Badge>}
          </div>
        );
      },
    },
    {
      id: "size",
      header: "Size",
      align: "right",
      className: "sm:w-24 tabular text-ink-muted",
      sortValue: (f) => f.size_bytes,
      cell: (f) => formatBytes(f.size_bytes),
    },
    {
      id: "by",
      header: "Uploaded by",
      className: "sm:w-40 text-ink-muted",
      sortValue: (f) => f.uploaded_by_name,
      cell: (f) => f.uploaded_by_name ?? "Someone who left",
    },
    {
      id: "date",
      header: "Date",
      className: "sm:w-32 text-ink-muted",
      sortValue: (f) => f.created_at,
      cell: (f) => <span className="tabular">{formatDate(f.created_at)}</span>,
    },
    {
      id: "actions",
      header: "",
      align: "right",
      className: "sm:w-24 max-sm:justify-end",
      cell: (f) => (
        <div className="flex justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label={`Download ${f.filename}`}
            disabled={f.status !== "ready" || downloading === f.id}
            onClick={() => void download(f)}
          >
            <Download />
          </Button>
          {f.can_delete && (
            <Button
              variant="ghost"
              size="icon"
              className="size-8 hover:text-danger"
              aria-label={`Delete ${f.filename}`}
              onClick={() => setDeleting(f)}
            >
              <Trash2 />
            </Button>
          )}
        </div>
      ),
    },
  ];

  const table = useDataTable({
    rows: files,
    columns,
    searchText: (f) => `${f.filename} ${f.uploaded_by_name ?? ""}`,
    initialSort: { id: "date", direction: "desc" },
  });

  return (
    <>
      <DataTable
        table={table}
        label="Files"
        searchLabel="Search files"
        rowKey={(f) => f.id}
        rowProps={(f) => ({ "data-file": f.filename })}
        empty={
          <EmptyState
            icon={FolderOpen}
            title="No files yet"
            description="Files you upload are stored safely for this workspace. Everyone in the team can see and download them."
            action={
              canUpload ? (
                <Button onClick={onChoose}>
                  <Upload aria-hidden="true" />
                  Upload a file
                </Button>
              ) : undefined
            }
          />
        }
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete “${deleting?.filename ?? ""}”?`}
        description="The file is deleted right away for everyone in this workspace. This can't be undone."
        confirmLabel="Delete file"
        busyLabel="Deleting…"
        onConfirm={async () => {
          if (!deleting) return;
          await unwrap(
            api.DELETE("/api/files/{file_id}", { params: { path: { file_id: deleting.id } } }),
          );
          toast.success(`“${deleting.filename}” deleted.`);
          onChange();
        }}
      />
    </>
  );
}
