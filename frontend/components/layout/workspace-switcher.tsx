"use client";

import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/session-provider";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { api, errorMessage, unwrap } from "@/lib/api";

const ROLE_LABEL = { owner: "Owner", admin: "Admin", member: "Member" } as const;

/** Shows the active workspace; switch to another one or create a new one. */
export function WorkspaceSwitcher() {
  const router = useRouter();
  const { organizations, activeOrganization } = useSession();
  const [creating, setCreating] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);

  async function switchTo(id: string) {
    if (id === activeOrganization.id) return;
    try {
      await unwrap(api.PUT("/api/auth/session/organization", { body: { organization_id: id } }));
      router.refresh();
    } catch (err) {
      setSwitchError(errorMessage(err));
    }
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label={`Workspace: ${activeOrganization.name}. Switch workspace`}
          className="flex h-9 min-w-0 items-center gap-2 rounded-control px-2.5 text-sm font-medium hover:bg-surface-sunken"
        >
          <span className="truncate">{activeOrganization.name}</span>
          <ChevronsUpDown className="size-3.5 shrink-0 text-ink-muted" aria-hidden="true" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="min-w-64">
          <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
          {organizations.map((org) => (
            <DropdownMenuItem key={org.id} onSelect={() => void switchTo(org.id)}>
              <span className="min-w-0 flex-1 truncate">{org.name}</span>
              <span className="text-xs text-ink-muted">{ROLE_LABEL[org.role]}</span>
              <Check
                className={org.id === activeOrganization.id ? "text-accent" : "invisible"}
                aria-label={org.id === activeOrganization.id ? "Current workspace" : undefined}
              />
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => setCreating(true)}>
            <Plus />
            Create workspace
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {switchError && (
        <span className="sr-only" role="alert">
          {switchError}
        </span>
      )}
      <CreateWorkspaceDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}

function CreateWorkspaceDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("name") ?? "").trim();
    if (!name) return setError("Give the workspace a name.");
    setBusy(true);
    setError(null);
    try {
      await unwrap(api.POST("/api/organizations", { body: { name } }));
      onOpenChange(false);
      router.refresh(); // the new workspace is now the active one
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Create a workspace"
        description="A separate space with its own data, for example one per client or team."
      >
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          {error && <Alert tone="error">{error}</Alert>}
          <Field label="Workspace name">
            {(a) => <Input {...a} autoFocus maxLength={80} name="name" placeholder="Acme GmbH" />}
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Creating…" : "Create workspace"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
