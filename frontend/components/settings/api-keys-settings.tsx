"use client";

import { Check, Copy, KeyRound } from "lucide-react";
import { useState } from "react";

import { ApiErrorAlert } from "@/components/billing/api-error-alert";
import { useSession } from "@/components/session-provider";
import { NoAccess, Section } from "@/components/settings/section";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { toast } from "@/components/ui/toast";
import { useApiData } from "@/hooks/use-api-data";
import { useDataTable, type Column } from "@/hooks/use-data-table";
import { useForm } from "@/hooks/use-form";
import { api, unwrap, type ApiKey, type ApiKeyCreated, type ApiKeyScope } from "@/lib/api";
import { formatDate, formatRelative } from "@/lib/format";
import { maxLength, required, rules } from "@/lib/validation";

/** What each scope lets a key do. Products add their scopes here and in the backend. */
const SCOPES: { value: ApiKeyScope; label: string; hint: string }[] = [
  { value: "jobs:read", label: "Read jobs", hint: "See background jobs and their progress." },
  { value: "jobs:write", label: "Start jobs", hint: "Start new background jobs." },
];

const EXPIRY: { label: string; days: number | null }[] = [
  { label: "Never", days: null },
  { label: "In 30 days", days: 30 },
  { label: "In 90 days", days: 90 },
  { label: "In 1 year", days: 365 },
];

/** Settings → API keys: create, copy once, see usage, revoke. */
export function ApiKeysSettings() {
  const { can } = useSession();
  const keys = useApiData(async () =>
    can("api_keys:manage")
      ? (await unwrap(api.GET("/api/organizations/current/api-keys"))).items
      : [],
  );
  const [created, setCreated] = useState<{ key: ApiKeyCreated; origin: string } | null>(null);

  if (!can("api_keys:manage")) {
    return <NoAccess>Only owners and admins can see and create API keys.</NoAccess>;
  }
  return (
    <div className="space-y-12">
      <Section
        title="Create an API key"
        description="Keys let your own scripts and other tools use this workspace through the REST API. A key belongs to the workspace, not to you: it keeps working if you leave."
      >
        {created ? (
          <KeyReveal
            created={created.key}
            origin={created.origin}
            onDone={() => setCreated(null)}
          />
        ) : (
          <CreateKeyForm
            onCreated={(key) => {
              setCreated({ key, origin: window.location.origin });
              void keys.reload();
            }}
          />
        )}
      </Section>
      <Section title="Active keys">
        <KeyList keys={keys.data} error={keys.error} onChange={() => void keys.reload()} />
      </Section>
    </div>
  );
}

function CreateKeyForm({ onCreated }: { onCreated: (key: ApiKeyCreated) => void }) {
  const [scopes, setScopes] = useState<ApiKeyScope[]>(["jobs:read"]);
  const [scopeError, setScopeError] = useState<string | null>(null);
  const form = useForm({
    initial: { name: "", expiry: "0" },
    validate: {
      name: rules(
        required("Give the key a name, for example the tool that uses it."),
        maxLength(80),
      ),
    },
    onSubmit: async ({ name, expiry }) => {
      if (scopes.length === 0) {
        setScopeError("Choose at least one thing the key may do.");
        return;
      }
      const days = Number(expiry);
      const created = await unwrap(
        api.POST("/api/organizations/current/api-keys", {
          body: { name: name.trim(), scopes, expires_in_days: days > 0 ? days : null },
        }),
      );
      form.reset();
      setScopes(["jobs:read"]);
      onCreated(created);
    },
  });

  function toggle(scope: ApiKeyScope, on: boolean) {
    setScopeError(null);
    setScopes((prev) => (on ? [...prev, scope] : prev.filter((s) => s !== scope)));
  }

  return (
    <form {...form.formProps} aria-label="Create an API key" className="space-y-5">
      {form.formError && <ApiErrorAlert message={form.formError} cause={form.formErrorCause} />}
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_10rem]">
        <Field
          label="Name"
          error={form.errors.name}
          hint="Where the key is used, e.g. “Zapier” or “Nightly import”."
        >
          {(a) => <Input {...a} {...form.field("name")} maxLength={80} autoComplete="off" />}
        </Field>
        <Field label="Expires">
          {(a) => (
            <Select {...a} {...form.field("expiry")}>
              {EXPIRY.map((e) => (
                <option key={e.label} value={e.days ?? 0}>
                  {e.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      <fieldset className="space-y-2" aria-describedby={scopeError ? "scope-error" : undefined}>
        <legend className="mb-1 text-sm font-medium">What the key may do</legend>
        {SCOPES.map((scope) => (
          <label key={scope.value} className="flex items-start gap-3 text-sm">
            <input
              type="checkbox"
              name="scopes"
              value={scope.value}
              checked={scopes.includes(scope.value)}
              onChange={(e) => toggle(scope.value, e.target.checked)}
              className="mt-0.5 size-4 accent-[var(--accent)]"
            />
            <span>
              <span className="font-medium">{scope.label}</span>
              <span className="block text-ink-muted">{scope.hint}</span>
            </span>
          </label>
        ))}
        {scopeError && (
          <p id="scope-error" className="text-xs text-danger">
            {scopeError}
          </p>
        )}
      </fieldset>
      <Button type="submit" disabled={form.submitting}>
        <KeyRound aria-hidden="true" />
        {form.submitting ? "Creating…" : "Create key"}
      </Button>
    </form>
  );
}

/** The one moment the secret is visible. */
function KeyReveal({
  created,
  origin,
  onDone,
}: {
  created: ApiKeyCreated;
  origin: string;
  onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(created.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard blocked (e.g. no permission): the text is selectable, copy by hand.
      setCopied(false);
    }
  }

  return (
    <div
      className="space-y-4 rounded-menu border border-accent/40 bg-accent-soft p-5"
      aria-label="Your new API key"
      role="region"
    >
      <div className="space-y-1">
        <p className="font-semibold">“{created.name}” is ready. Copy the key now.</p>
        <p className="text-sm text-ink-muted">
          For your safety we only store a fingerprint of it, so it can&apos;t be shown again. Lost
          it? Revoke it and create a new one.
        </p>
      </div>
      <div className="flex flex-wrap items-stretch gap-2">
        <code
          data-testid="new-api-key"
          className="min-w-0 flex-1 rounded-control border border-line-strong bg-surface px-3 py-2.5 font-mono text-sm break-all select-all"
        >
          {created.key}
        </code>
        <Button variant="secondary" className="h-auto" onClick={() => void copy()}>
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? "Copied" : "Copy key"}
        </Button>
      </div>
      <div className="space-y-1.5">
        <p className="text-sm text-ink-muted">Try it:</p>
        <pre className="overflow-x-auto rounded-control bg-surface px-3 py-2.5 font-mono text-xs">
          {`curl -H "Authorization: Bearer ${created.key}" ${origin}/api/jobs`}
        </pre>
      </div>
      <Button onClick={onDone}>I copied the key</Button>
    </div>
  );
}

function KeyList({
  keys,
  error,
  onChange,
}: {
  keys: ApiKey[] | null;
  error: string | null;
  onChange: () => void;
}) {
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  const columns: Column<ApiKey>[] = [
    {
      id: "name",
      header: "Name",
      hideLabelOnPhone: true,
      sortValue: (k) => k.name,
      cell: (k) => (
        <div className="min-w-0 space-y-0.5">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-medium">{k.name}</span>
            <code className="font-mono text-xs text-ink-muted">{k.prefix}…</code>
            {k.expired && <Badge tone="danger">Expired</Badge>}
          </p>
          <p className="text-xs text-ink-muted">
            {k.scopes.map((s) => SCOPES.find((x) => x.value === s)?.label ?? s).join(", ")}. Created{" "}
            {formatDate(k.created_at)}
            {k.created_by_name && ` by ${k.created_by_name}`}.
            {k.expires_at && !k.expired && ` Expires ${formatDate(k.expires_at)}.`}
          </p>
        </div>
      ),
    },
    {
      id: "last_used",
      header: "Last used",
      className: "sm:w-36 text-ink-muted",
      sortValue: (k) => k.last_used_at,
      cell: (k) => (k.last_used_at ? formatRelative(k.last_used_at) : "Never"),
    },
    {
      id: "actions",
      header: "",
      align: "right",
      className: "sm:w-24 max-sm:justify-end",
      cell: (k) => (
        <Button variant="ghost" size="sm" onClick={() => setRevoking(k)}>
          Revoke
        </Button>
      ),
    },
  ];
  const table = useDataTable({
    rows: keys,
    columns,
    searchText: (k) => `${k.name} ${k.prefix} ${k.created_by_name ?? ""}`,
    initialSort: { id: "name", direction: "asc" },
  });

  if (keys === null && error) return <Alert tone="error">Could not load API keys: {error}</Alert>;
  return (
    <>
      <DataTable
        table={table}
        label="API keys"
        searchLabel="Search keys"
        rowKey={(k) => k.id}
        rowProps={(k) => ({ "data-key-name": k.name })}
        empty={
          <EmptyState
            icon={KeyRound}
            title="No API keys yet"
            description="Create a key above when a script or another tool needs to work with this workspace."
          />
        }
      />
      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => !open && setRevoking(null)}
        title={`Revoke “${revoking?.name ?? ""}”?`}
        description="Everything that uses this key stops working immediately. This can't be undone."
        confirmLabel="Revoke key"
        busyLabel="Revoking…"
        onConfirm={async () => {
          if (!revoking) return;
          await unwrap(
            api.DELETE("/api/organizations/current/api-keys/{key_id}", {
              params: { path: { key_id: revoking.id } },
            }),
          );
          toast.success(`“${revoking.name}” was revoked.`);
          onChange();
        }}
      />
    </>
  );
}
