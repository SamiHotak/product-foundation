"use client";

import { createContext, useContext } from "react";

import type { Me, Organization, Permission } from "@/lib/api";

type SessionValue = Me & {
  activeOrganization: Organization;
  /** True if you may do this in the active workspace (rules: backend/app/core/permissions.py). */
  can: (permission: Permission) => boolean;
};

const SessionContext = createContext<SessionValue | null>(null);

/**
 * The signed-in user and workspaces, loaded on the server in app/(app)/layout.tsx.
 * After a change (switch workspace, role change, sign out) call router.refresh() to reload it.
 *
 * `can()` only hides buttons and pages. The backend checks every request itself.
 */
export function SessionProvider({ me, children }: { me: Me; children: React.ReactNode }) {
  const activeOrganization =
    me.organizations.find((o) => o.id === me.active_organization_id) ?? me.organizations[0]!;
  const allowed = new Set(me.permissions);
  return (
    <SessionContext.Provider
      value={{ ...me, activeOrganization, can: (permission) => allowed.has(permission) }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>.");
  return value;
}
