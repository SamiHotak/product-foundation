"use client";

import { MoreHorizontal, UserPlus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/session-provider";
import { NoAccess, Section } from "@/components/settings/section";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useApiData } from "@/hooks/use-api-data";
import { api, errorMessage, fieldErrors, unwrap, type Invite, type Member } from "@/lib/api";
import { formatDate, formatRelative } from "@/lib/format";

const ROLE_LABEL = { owner: "Owner", admin: "Admin", member: "Member" } as const;

const ROLE_HELP =
  "Admins manage the team, API keys and the audit log. Members use the product. " +
  "The owner can also delete the workspace or hand it to someone else.";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return (
    ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts.at(-1)?.[0] ?? "") : "")).toUpperCase() ||
    "?"
  );
}

/** Settings → Workspace: name, team, invites, leave. */
export function WorkspaceSettings() {
  const { can } = useSession();
  const members = useApiData(
    async () => (await unwrap(api.GET("/api/organizations/current/members"))).items,
  );
  const invites = useApiData(async () =>
    can("members:invite")
      ? (await unwrap(api.GET("/api/organizations/current/invites"))).items
      : [],
  );
  return (
    <div className="space-y-12">
      <WorkspaceName />
      <Section title="Members" description={ROLE_HELP}>
        {can("members:invite") && <InviteForm onSent={() => void invites.reload()} />}
        <MemberList
          members={members.data}
          error={members.error}
          onChange={() => void members.reload()}
        />
        {can("members:invite") && (
          <OpenInvites
            invites={invites.data}
            error={invites.error}
            onChange={() => void invites.reload()}
          />
        )}
      </Section>
      <LeaveWorkspace />
    </div>
  );
}

// --- name -----------------------------------------------------------------------------------

function WorkspaceName() {
  const router = useRouter();
  const { activeOrganization, can } = useSession();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("name") ?? "").trim();
    if (!name) return setMessage({ tone: "error", text: "Give the workspace a name." });
    setBusy(true);
    setMessage(null);
    try {
      await unwrap(api.PATCH("/api/organizations/current", { body: { name } }));
      setMessage({ tone: "success", text: "Name saved." });
      router.refresh();
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  if (!can("org:update")) {
    return (
      <Section title="Workspace name">
        <p className="text-sm font-medium">{activeOrganization.name}</p>
      </Section>
    );
  }
  return (
    <Section title="Workspace name" description="Everyone in the workspace sees this name.">
      <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3" noValidate>
        <Field label="Name" className="min-w-0 flex-1 basis-60">
          {(a) => (
            <Input {...a} name="name" maxLength={80} defaultValue={activeOrganization.name} />
          )}
        </Field>
        <Button type="submit" variant="secondary" disabled={busy}>
          {busy ? "Saving…" : "Save name"}
        </Button>
      </form>
      {message && <Alert tone={message.tone}>{message.text}</Alert>}
    </Section>
  );
}

// --- invite ---------------------------------------------------------------------------------

function InviteForm({ onSent }: { onSent: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<Invite | null>(null);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const email = String(data.get("email") ?? "").trim();
    const role = data.get("role") === "admin" ? "admin" : "member";
    if (!/^\S+@\S+\.\S+$/.test(email)) return setError("Enter a valid email address.");
    setBusy(true);
    setError(null);
    setSent(null);
    try {
      setSent(
        await unwrap(api.POST("/api/organizations/current/invites", { body: { email, role } })),
      );
      form.reset();
      onSent();
    } catch (err) {
      setError(fieldErrors(err).email ?? errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      aria-label="Invite someone"
      className="space-y-3 rounded-menu border border-line bg-surface-sunken/60 p-4"
      noValidate
    >
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Invite by email" className="min-w-0 flex-1 basis-56">
          {(a) => (
            <Input
              {...a}
              type="email"
              name="email"
              autoComplete="off"
              placeholder="name@company.com"
            />
          )}
        </Field>
        <Field label="Role" className="w-32">
          {(a) => (
            <Select {...a} name="role" defaultValue="member">
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </Select>
          )}
        </Field>
        <Button type="submit" disabled={busy}>
          <UserPlus aria-hidden="true" />
          {busy ? "Sending…" : "Send invite"}
        </Button>
      </div>
      {error && <Alert tone="error">{error}</Alert>}
      {sent && (
        <Alert tone="success">
          Invite sent to {sent.email}. The link works until {formatDate(sent.expires_at)}.
        </Alert>
      )}
    </form>
  );
}

// --- members --------------------------------------------------------------------------------

type Pending = { kind: "remove"; member: Member } | { kind: "owner"; member: Member } | null;

function MemberList({
  members,
  error,
  onChange,
}: {
  members: Member[] | null;
  error: string | null;
  onChange: () => void;
}) {
  const router = useRouter();
  const { can } = useSession();
  const [pending, setPending] = useState<Pending>(null);
  const [rowError, setRowError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function changeRole(member: Member, role: "admin" | "member") {
    setBusyId(member.user_id);
    setRowError(null);
    try {
      await unwrap(
        api.PATCH("/api/organizations/current/members/{user_id}", {
          params: { path: { user_id: member.user_id } },
          body: { role },
        }),
      );
      onChange();
    } catch (err) {
      setRowError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  if (members === null) {
    if (error) return <Alert tone="error">Could not load the team: {error}</Alert>;
    return (
      <ul className="divide-y divide-line rounded-menu border border-line" aria-busy="true">
        {[0, 1].map((i) => (
          <li key={i} className="flex items-center gap-3 px-4 py-3">
            <Skeleton className="size-8 rounded-full" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-56" />
            </div>
          </li>
        ))}
      </ul>
    );
  }

  const manage = can("members:manage");
  const transfer = can("ownership:transfer");
  return (
    <>
      {rowError && <Alert tone="error">{rowError}</Alert>}
      <ul className="divide-y divide-line rounded-menu border border-line" aria-label="Members">
        {members.map((m) => {
          const editable = manage && !m.is_you && m.role !== "owner";
          const hasMenu = (editable || (transfer && !m.is_you)) && m.role !== "owner";
          return (
            <li
              key={m.user_id}
              className="flex items-center gap-3 px-4 py-3"
              data-member-email={m.email}
            >
              <span
                aria-hidden="true"
                className="grid size-8 shrink-0 place-items-center self-start rounded-full bg-accent-soft text-xs font-semibold text-accent sm:self-center"
              >
                {initials(m.name)}
              </span>
              <div className="min-w-0 flex-1 sm:flex sm:items-center sm:gap-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    {m.name}
                    {m.is_you && <span className="font-normal text-ink-muted"> (you)</span>}
                  </p>
                  <p className="truncate text-xs text-ink-muted">
                    {m.email}, joined {formatDate(m.joined_at)}
                  </p>
                </div>
                <div className="mt-2 sm:mt-0 sm:w-32">
                  {editable ? (
                    <Select
                      aria-label={`Role of ${m.name}`}
                      className="w-32"
                      value={m.role}
                      disabled={busyId === m.user_id}
                      onChange={(e) => void changeRole(m, e.target.value as "admin" | "member")}
                    >
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                    </Select>
                  ) : (
                    <span className="block text-sm text-ink-muted sm:text-right">
                      {ROLE_LABEL[m.role]}
                    </span>
                  )}
                </div>
              </div>
              {hasMenu ? (
                <DropdownMenu>
                  <DropdownMenuTrigger
                    aria-label={`More actions for ${m.name}`}
                    className="grid size-9 shrink-0 place-items-center rounded-control text-ink-muted hover:bg-surface-sunken hover:text-ink"
                  >
                    <MoreHorizontal className="size-4" />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {transfer && (
                      <DropdownMenuItem onSelect={() => setPending({ kind: "owner", member: m })}>
                        Make owner
                      </DropdownMenuItem>
                    )}
                    {editable && (
                      <DropdownMenuItem
                        className="text-danger"
                        onSelect={() => setPending({ kind: "remove", member: m })}
                      >
                        Remove from workspace
                      </DropdownMenuItem>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : (
                <span className="hidden size-9 shrink-0 sm:block" aria-hidden="true" />
              )}
            </li>
          );
        })}
      </ul>

      <ConfirmDialog
        open={pending?.kind === "remove"}
        onOpenChange={(open) => !open && setPending(null)}
        title={`Remove ${pending?.member.name ?? ""}?`}
        description="They lose access to this workspace right away. Their account stays, and you can invite them again later."
        confirmLabel="Remove"
        busyLabel="Removing…"
        onConfirm={async () => {
          if (!pending) return;
          await unwrap(
            api.DELETE("/api/organizations/current/members/{user_id}", {
              params: { path: { user_id: pending.member.user_id } },
            }),
          );
          onChange();
        }}
      />
      <ConfirmDialog
        open={pending?.kind === "owner"}
        onOpenChange={(open) => !open && setPending(null)}
        title={`Make ${pending?.member.name ?? ""} the owner?`}
        description="There is one owner per workspace. You become an admin and can't undo this yourself: only the new owner can give ownership back."
        confirmLabel="Make owner"
        busyLabel="Transferring…"
        tone="primary"
        onConfirm={async () => {
          if (!pending) return;
          await unwrap(
            api.POST("/api/organizations/current/transfer-ownership", {
              body: { user_id: pending.member.user_id },
            }),
          );
          onChange();
          router.refresh(); // your own permissions changed
        }}
      />
    </>
  );
}

// --- open invites ---------------------------------------------------------------------------

function OpenInvites({
  invites,
  error,
  onChange,
}: {
  invites: Invite[] | null;
  error: string | null;
  onChange: () => void;
}) {
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const [cancelling, setCancelling] = useState<Invite | null>(null);

  async function resend(invite: Invite) {
    setMessage(null);
    try {
      await unwrap(
        api.POST("/api/organizations/current/invites/{invite_id}/resend", {
          params: { path: { invite_id: invite.id } },
        }),
      );
      setMessage({ tone: "success", text: `Sent a new link to ${invite.email}.` });
      onChange();
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    }
  }

  if (invites === null) {
    return error ? <Alert tone="error">Could not load invites: {error}</Alert> : null;
  }
  if (invites.length === 0) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">Waiting for an answer</h3>
      {message && <Alert tone={message.tone}>{message.text}</Alert>}
      <ul
        className="divide-y divide-line rounded-menu border border-line"
        aria-label="Open invites"
      >
        {invites.map((invite) => (
          <li
            key={invite.id}
            className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3"
            data-invite-email={invite.email}
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{invite.email}</p>
              <p className="text-xs text-ink-muted">
                {ROLE_LABEL[invite.role]}
                {invite.invited_by_name && `, invited by ${invite.invited_by_name}`}. Link expires{" "}
                {formatRelative(invite.expires_at)}.
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => void resend(invite)}>
              Send again
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setCancelling(invite)}>
              Cancel invite
            </Button>
          </li>
        ))}
      </ul>
      <ConfirmDialog
        open={cancelling !== null}
        onOpenChange={(open) => !open && setCancelling(null)}
        title="Cancel this invite?"
        description={`The link sent to ${cancelling?.email ?? ""} stops working.`}
        confirmLabel="Cancel invite"
        busyLabel="Cancelling…"
        onConfirm={async () => {
          if (!cancelling) return;
          await unwrap(
            api.DELETE("/api/organizations/current/invites/{invite_id}", {
              params: { path: { invite_id: cancelling.id } },
            }),
          );
          onChange();
        }}
      />
    </div>
  );
}

// --- leave ----------------------------------------------------------------------------------

function LeaveWorkspace() {
  const router = useRouter();
  const { activeOrganization } = useSession();
  const [open, setOpen] = useState(false);
  if (activeOrganization.role === "owner") {
    return (
      <Section title="Leave workspace">
        <NoAccess>
          You own this workspace, so you can&apos;t leave it. Make someone else the owner first (in
          the member list above), or delete the workspace under Privacy.
        </NoAccess>
      </Section>
    );
  }
  return (
    <Section
      title="Leave workspace"
      description="You lose access to its data. Someone has to invite you again to come back."
    >
      <div>
        <Button variant="secondary" onClick={() => setOpen(true)}>
          Leave {activeOrganization.name}
        </Button>
      </div>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Leave ${activeOrganization.name}?`}
        confirmLabel="Leave workspace"
        busyLabel="Leaving…"
        onConfirm={async () => {
          await unwrap(api.POST("/api/organizations/current/leave"));
          router.replace("/dashboard");
          router.refresh();
        }}
      />
    </Section>
  );
}
