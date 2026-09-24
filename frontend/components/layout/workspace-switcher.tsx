"use client";

import { ChevronsUpDown, Plus } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * Workspace (organization) switcher. Phase 1 shows a single placeholder workspace;
 * phase 2 loads the user's real organizations and switches between them.
 */
export function WorkspaceSwitcher() {
  const current = "Personal workspace";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex h-9 min-w-0 items-center gap-2 rounded-control px-2.5 text-sm font-medium hover:bg-surface-sunken">
        <span className="truncate">{current}</span>
        <ChevronsUpDown className="size-3.5 shrink-0 text-ink-muted" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
        <DropdownMenuItem>{current}</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled>
          <Plus />
          Create workspace
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
