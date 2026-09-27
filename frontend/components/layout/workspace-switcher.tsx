"use client";

import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/session-provider";
import { CreateWorkspaceDialog } from "@/components/layout/create-workspace-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "@/components/ui/toast";
import { api, errorMessage, unwrap } from "@/lib/api";

const ROLE_LABEL = { owner: "Owner", admin: "Admin", member: "Member" } as const;

/** Shows the active workspace; switch to another one or create a new one. */
export function WorkspaceSwitcher() {
  const router = useRouter();
  const { organizations, activeOrganization } = useSession();
  const [creating, setCreating] = useState(false);

  async function switchTo(id: string) {
    if (id === activeOrganization.id) return;
    try {
      await unwrap(api.PUT("/api/auth/session/organization", { body: { organization_id: id } }));
      router.refresh();
    } catch (err) {
      toast.error("Could not switch the workspace.", { description: errorMessage(err) });
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
      <CreateWorkspaceDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}
