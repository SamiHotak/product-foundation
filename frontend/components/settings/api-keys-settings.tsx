"use client";

import { Check, Copy, KeyRound } from "lucide-react";
import { useState } from "react";

import { useSession } from "@/components/session-provider";
import { NoAccess, Section } from "@/components/settings/section";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiData } from "@/hooks/use-api-data";
import {
  api,
  errorMessage,
  unwrap,
  type ApiKey,
  type ApiKeyCreated,
  type ApiKeyScope,
} from "@/lib/api";
import { formatDate, formatRelative } from "@/lib/format";

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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const name = String(data.get("name") ?? "").trim();
    const scopes = data.getAll("scopes").map(String) as ApiKeyScope[];
    const days = Number(data.get("expiry"));
    if (!name) return setError("Give the key a name, for example the tool that uses it.");
    if (scopes.length === 0) return setError("Choose at least one thing the key may do.");
    setBusy(true);
    setError(null);
    try {
      onCreated(
        await unwrap(
          api.POST("/api/organizations/current/api-keys", {
            body: { name, scopes, expires_in_days: days > 0 ? days : null },
          }),
        ),
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} aria-label="Create an API key" className="space-y-5" noValidate>
      {error && <Alert tone="error">{error}</Alert>}
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_10rem]">
        <Field label="Name" hint="Where the key is used, e.g. “Zapier” or “Nightly import”.">
          {(a) => <Input {...a} name="name" maxLength={80} autoComplete="off" />}
        </Field>
        <Field label="Expires">
          {(a) => (
            <Select {...a} name="expiry" defaultValue="0">
              {EXPIRY.map((e) => (
                <option key={e.label} value={e.days ?? 0}>
                  {e.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-medium">What the key may do</legend>
        {SCOPES.map((scope) => (
          <label key={scope.value} className="flex items-start gap-3 text-sm">
            <input
              type="checkbox"
              name="scopes"
              value={scope.value}
              defaultChecked={scope.value === "jobs:read"}
              className="mt-0.5 size-4 accent-[var(--accent)]"
            />
            <span>
              <span className="font-medium">{scope.label}</span>
              <span className="block text-ink-muted">{scope.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <Button type="submit" disabled={busy}>
        <KeyRound aria-hidden="true" />
        {busy ? "Creating…" : "Create key"}
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

  if (keys === null) {
    if (error) return <Alert tone="error">Could not load API keys: {error}</Alert>;
    return <Skeleton className="h-16 w-full" />;
  }
  if (keys.length === 0) {
    return (
      <EmptyState
        icon={KeyRound}
        title="No API keys yet"
        description="Create a key above when a script or another tool needs to work with this workspace."
      />
    );
  }
  return (
    <>
      <ul className="divide-y divide-line rounded-menu border border-line" aria-label="API keys">
        {keys.map((key) => (
          <li
            key={key.id}
            className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3"
            data-key-name={key.name}
          >
            <div className="min-w-0 flex-1 space-y-0.5">
              <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
                <span className="font-medium">{key.name}</span>
                <code className="font-mono text-xs text-ink-muted">{key.prefix}…</code>
                {key.expired && <span className="text-xs font-medium text-danger">Expired</span>}
              </p>
              <p className="text-xs text-ink-muted">
                {key.scopes.map((s) => SCOPES.find((x) => x.value === s)?.label ?? s).join(", ")}.{" "}
                Created {formatDate(key.created_at)}
                {key.created_by_name && ` by ${key.created_by_name}`}.{" "}
                {key.last_used_at
                  ? `Last used ${formatRelative(key.last_used_at)}.`
                  : "Never used."}
                {key.expires_at && !key.expired && ` Expires ${formatDate(key.expires_at)}.`}
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setRevoking(key)}>
              Revoke
            </Button>
          </li>
        ))}
      </ul>
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
          onChange();
        }}
      />
    </>
  );
}
