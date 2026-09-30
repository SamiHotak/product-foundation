"use client";

import { Eye, Users } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/session-provider";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { useApiData } from "@/hooks/use-api-data";
import { useDataTable, type Column, type Filter } from "@/hooks/use-data-table";
import { api, unwrap, type AdminUser } from "@/lib/api";
import { formatDate, formatRelative } from "@/lib/format";

const KIND_FILTER: Filter<AdminUser> = {
  id: "kind",
  label: "Kind",
  allLabel: "Everyone",
  options: [
    { value: "admin", label: "App admins" },
    { value: "unverified", label: "Email not confirmed" },
    { value: "deleting", label: "Being deleted" },
  ],
  test: (u, value) =>
    value === "admin"
      ? u.is_superuser
      : value === "unverified"
        ? !u.email_verified
        : u.deletion_scheduled_at !== null,
};

/** Admin → Users, with "View as" (impersonation) for support. */
export function AdminUsersView() {
  const { user: me } = useSession();
  const router = useRouter();
  const users = useApiData(async () => (await unwrap(api.GET("/api/admin/users"))).items);
  const [viewing, setViewing] = useState<AdminUser | null>(null);

  const columns: Column<AdminUser>[] = [
    {
      id: "name",
      header: "Name",
      hideLabelOnPhone: true,
      sortValue: (u) => u.name,
      cell: (u) => (
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-1.5 font-medium">
            <span className="truncate">{u.name}</span>
            {u.is_superuser && <Badge tone="accent">Admin</Badge>}
            {u.is_demo && <Badge>Demo</Badge>}
            {!u.email_verified && <Badge tone="warning">Unconfirmed</Badge>}
            {!u.is_active && <Badge tone="danger">Disabled</Badge>}
          </p>
          <p className="truncate text-xs text-ink-muted">{u.email}</p>
        </div>
      ),
    },
    {
      id: "workspaces",
      header: "Workspaces",
      align: "right",
      className: "sm:w-28 tabular",
      sortValue: (u) => u.workspaces,
      cell: (u) => u.workspaces,
    },
    {
      id: "login",
      header: "Last sign-in",
      className: "sm:w-36 text-ink-muted",
      sortValue: (u) => u.last_login_at,
      cell: (u) => (u.last_login_at ? formatRelative(u.last_login_at) : "Never"),
    },
    {
      id: "created",
      header: "Signed up",
      className: "sm:w-32 text-ink-muted",
      sortValue: (u) => u.created_at,
      cell: (u) => <span className="tabular">{formatDate(u.created_at)}</span>,
    },
    {
      id: "actions",
      header: "",
      align: "right",
      className: "sm:w-28 max-sm:justify-end",
      cell: (u) =>
        u.is_superuser || u.id === me.id || !u.is_active ? null : (
          <Button variant="secondary" size="sm" onClick={() => setViewing(u)}>
            <Eye aria-hidden="true" />
            View as
          </Button>
        ),
    },
  ];

  const table = useDataTable({
    rows: users.data,
    columns,
    searchText: (u) => `${u.name} ${u.email}`,
    filters: [KIND_FILTER],
    initialSort: { id: "created", direction: "desc" },
    pageSize: 25,
  });

  if (users.data === null && users.error)
    return <Alert tone="error">Could not load: {users.error}</Alert>;
  return (
    <>
      <DataTable
        table={table}
        label="Users"
        searchLabel="Search name or email"
        rowKey={(u) => u.id}
        rowProps={(u) => ({ "data-user-email": u.email })}
        empty={<EmptyState icon={Users} title="No users yet" description="Sign-ups appear here." />}
      />
      <ConfirmDialog
        open={viewing !== null}
        onOpenChange={(open) => !open && setViewing(null)}
        tone="primary"
        title={`View the app as ${viewing?.name ?? ""}?`}
        description="For support: you see and do what they can, for a limited time (1 hour by default). Passwords, billing, API keys, exports and deleting stay blocked. It is written to the audit log of their workspaces, so they can see it."
        confirmLabel="View as this user"
        busyLabel="Switching…"
        onConfirm={async () => {
          if (!viewing) return;
          await unwrap(
            api.POST("/api/admin/users/{user_id}/impersonate", {
              params: { path: { user_id: viewing.id } },
            }),
          );
          // The app reloads as them (a new user = the whole app shell is rebuilt).
          router.replace("/dashboard");
          router.refresh();
        }}
      />
    </>
  );
}
