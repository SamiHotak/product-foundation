"use client";

import { MailPlus, MoreHorizontal, UserPlus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/session-provider";
import { Section } from "@/components/settings/section";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { toast } from "@/components/ui/toast";
import { useApiData } from "@/hooks/use-api-data";
import { useDataTable, type Column, type Filter } from "@/hooks/use-data-table";
import { useForm } from "@/hooks/use-form";
import { api, errorMessage, unwrap, type Invite, type Member, type Role } from "@/lib/api";
import { formatDate, formatRelative } from "@/lib/format";
import { email, required, rules } from "@/lib/validation";

const ROLE_LABEL = { owner: "Owner", admin: "Admin", member: "Member" } as const;
const ROLE_RANK: Record<Role, number> = { owner: 0, admin: 1, member: 2 };

const ROLE_HELP =
  "Admins manage the team, API keys and the audit log. Members use the product. " +
  "The owner can also delete the workspace, manage billing, or hand it to someone else.";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return (
    ((parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts.at(-1)?.[0] ?? "") : "")).toUpperCase() ||
    "?"
  );
}

/** Settings → Members: invite people, change roles, remove, hand over ownership. */
export function MembersSettings() {
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
      {can("members:invite") && (
        <Section title="Invite someone" id="invite" description={ROLE_HELP}>
          <InviteForm onSent={() => void invites.reload()} />
        </Section>
      )}
      <Section
        title="Members"
        description={can("members:invite") ? undefined : ROLE_HELP}
        id="members-title"
      >
        <MembersTable
          members={members.data}
          error={members.error}
          onChange={() => void members.reload()}
          setMembers={members.setData}
        />
      </Section>
      {can("members:invite") && (
        <OpenInvites
          invites={invites.data}
          error={invites.error}
          onChange={() => void invites.reload()}
        />
      )}
    </div>
  );
}

// --- invite ---------------------------------------------------------------------------------

function InviteForm({ onSent }: { onSent: () => void }) {
  const form = useForm({
    initial: { email: "", role: "member" },
    validate: { email: rules(required("Enter an email address."), email()) },
    onSubmit: async (values) => {
      const role = values.role === "admin" ? "admin" : "member";
      const sent = await unwrap(
        api.POST("/api/organizations/current/invites", {
          body: { email: values.email.trim(), role },
        }),
      );
      form.reset();
      toast.success(`Invite sent to ${sent.email}.`, {
        description: `The link works until ${formatDate(sent.expires_at)}.`,
      });
      onSent();
    },
  });

  return (
    <form
      {...form.formProps}
      aria-label="Invite someone"
      className="space-y-3 rounded-menu border border-line bg-surface-sunken/60 p-4"
    >
      {form.formError && <Alert tone="error">{form.formError}</Alert>}
      <div className="flex flex-wrap items-start gap-3">
        <Field
          label="Invite by email"
          error={form.errors.email}
          className="min-w-0 flex-1 basis-56"
        >
          {(a) => (
            <Input
              {...a}
              {...form.field("email")}
              type="email"
              autoComplete="off"
              placeholder="name@company.com"
            />
          )}
        </Field>
        <Field label="Role" className="w-32">
          {(a) => (
            <Select {...a} {...form.field("role")}>
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </Select>
          )}
        </Field>
        <Button type="submit" disabled={form.submitting} className="mt-7">
          <UserPlus aria-hidden="true" />
          {form.submitting ? "Sending…" : "Send invite"}
        </Button>
      </div>
    </form>
  );
}

// --- members --------------------------------------------------------------------------------

type Pending = { kind: "remove"; member: Member } | { kind: "owner"; member: Member } | null;

const ROLE_FILTER: Filter<Member> = {
  id: "role",
  label: "Role",
  allLabel: "All roles",
  options: [
    { value: "owner", label: "Owner" },
    { value: "admin", label: "Admins" },
    { value: "member", label: "Members" },
  ],
  test: (m, value) => m.role === value,
};

function MembersTable({
  members,
  error,
  onChange,
  setMembers,
}: {
  members: Member[] | null;
  error: string | null;
  onChange: () => void;
  setMembers: (update: (prev: Member[] | null) => Member[] | null) => void;
}) {
  const router = useRouter();
  const { can } = useSession();
  const [pending, setPending] = useState<Pending>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const manage = can("members:manage");
  const transfer = can("ownership:transfer");

  async function changeRole(member: Member, role: "admin" | "member") {
    setBusyId(member.user_id);
    // Optimistic: show the new role right away, undo it if the API says no.
    setMembers(
      (prev) => prev?.map((m) => (m.user_id === member.user_id ? { ...m, role } : m)) ?? null,
    );
    try {
      await unwrap(
        api.PATCH("/api/organizations/current/members/{user_id}", {
          params: { path: { user_id: member.user_id } },
          body: { role },
        }),
      );
      toast.success(`${member.name} is now ${role === "admin" ? "an admin" : "a member"}.`);
    } catch (err) {
      setMembers(
        (prev) =>
          prev?.map((m) => (m.user_id === member.user_id ? { ...m, role: member.role } : m)) ??
          null,
      );
      toast.error("Could not change the role.", { description: errorMessage(err) });
    } finally {
      setBusyId(null);
      onChange();
    }
  }

  const columns: Column<Member>[] = [
    {
      id: "name",
      header: "Name",
      hideLabelOnPhone: true,
      sortValue: (m) => m.name,
      cell: (m) => (
        <div className="flex min-w-0 items-center gap-3">
          <span
            aria-hidden="true"
            className="grid size-8 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent"
          >
            {initials(m.name)}
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium">
              {m.name}
              {m.is_you && <span className="font-normal text-ink-muted"> (you)</span>}
            </p>
            <p className="truncate text-xs text-ink-muted">{m.email}</p>
          </div>
        </div>
      ),
    },
    {
      id: "role",
      header: "Role",
      className: "sm:w-36",
      sortValue: (m) => ROLE_RANK[m.role],
      cell: (m) =>
        manage && !m.is_you && m.role !== "owner" ? (
          <Select
            aria-label={`Role of ${m.name}`}
            className="w-32 [&_select]:h-8"
            value={m.role}
            disabled={busyId === m.user_id}
            onChange={(e) => void changeRole(m, e.target.value as "admin" | "member")}
          >
            <option value="member">Member</option>
            <option value="admin">Admin</option>
          </Select>
        ) : (
          <Badge tone={m.role === "owner" ? "accent" : "neutral"}>{ROLE_LABEL[m.role]}</Badge>
        ),
    },
    {
      id: "joined",
      header: "Joined",
      className: "sm:w-32 text-ink-muted",
      sortValue: (m) => m.joined_at,
      cell: (m) => <span className="tabular">{formatDate(m.joined_at)}</span>,
    },
    {
      id: "actions",
      header: "",
      align: "right",
      className: "sm:w-12 max-sm:justify-end",
      cell: (m) => {
        const editable = manage && !m.is_you && m.role !== "owner";
        const canTransfer = transfer && !m.is_you && m.role !== "owner";
        if (!editable && !canTransfer) return null;
        return (
          <DropdownMenu>
            <DropdownMenuTrigger
              aria-label={`More actions for ${m.name}`}
              className="grid size-8 place-items-center rounded-control text-ink-muted hover:bg-surface-sunken hover:text-ink"
            >
              <MoreHorizontal className="size-4" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {canTransfer && (
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
        );
      },
    },
  ];

  const table = useDataTable({
    rows: members,
    columns,
    searchText: (m) => `${m.name} ${m.email}`,
    filters: [ROLE_FILTER],
    initialSort: { id: "role", direction: "asc" },
  });

  if (members === null && error)
    return <Alert tone="error">Could not load the team: {error}</Alert>;

  return (
    <>
      <DataTable
        table={table}
        label="Members"
        searchLabel="Search members"
        rowKey={(m) => m.user_id}
        rowProps={(m) => ({ "data-member-email": m.email })}
      />
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
          toast.success(`${pending.member.name} was removed.`);
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
          toast.success(`${pending.member.name} is the owner now.`);
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
  const [cancelling, setCancelling] = useState<Invite | null>(null);

  async function resend(invite: Invite) {
    try {
      await unwrap(
        api.POST("/api/organizations/current/invites/{invite_id}/resend", {
          params: { path: { invite_id: invite.id } },
        }),
      );
      toast.success(`Sent a new link to ${invite.email}.`);
      onChange();
    } catch (err) {
      toast.error("Could not send the invite again.", { description: errorMessage(err) });
    }
  }

  const columns: Column<Invite>[] = [
    {
      id: "email",
      header: "Email",
      hideLabelOnPhone: true,
      sortValue: (i) => i.email,
      cell: (i) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{i.email}</p>
          {i.invited_by_name && (
            <p className="truncate text-xs text-ink-muted">Invited by {i.invited_by_name}</p>
          )}
        </div>
      ),
    },
    {
      id: "role",
      header: "Role",
      className: "sm:w-28",
      cell: (i) => <Badge>{ROLE_LABEL[i.role]}</Badge>,
    },
    {
      id: "expires",
      header: "Link expires",
      className: "sm:w-36 text-ink-muted",
      sortValue: (i) => i.expires_at,
      cell: (i) => formatRelative(i.expires_at),
    },
    {
      id: "actions",
      header: "",
      align: "right",
      className: "sm:w-56 max-sm:justify-end",
      cell: (i) => (
        <div className="flex justify-end gap-1">
          <Button variant="ghost" size="sm" onClick={() => void resend(i)}>
            Send again
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setCancelling(i)}>
            Cancel invite
          </Button>
        </div>
      ),
    },
  ];
  const table = useDataTable({
    rows: invites,
    columns,
    searchText: (i) => i.email,
    initialSort: { id: "expires", direction: "asc" },
  });

  return (
    <Section
      title="Waiting for an answer"
      description="Invites that nobody has accepted yet. Send again for a fresh link."
    >
      {invites === null && error && <Alert tone="error">Could not load invites: {error}</Alert>}
      <DataTable
        table={table}
        label="Open invites"
        searchLabel="Search invites"
        rowKey={(i) => i.id}
        rowProps={(i) => ({ "data-invite-email": i.email })}
        empty={
          <EmptyState
            icon={MailPlus}
            title="No open invites"
            description="People you invite show up here until they join."
          />
        }
      />
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
          toast.success(`The invite to ${cancelling.email} was cancelled.`);
          onChange();
        }}
      />
    </Section>
  );
}
