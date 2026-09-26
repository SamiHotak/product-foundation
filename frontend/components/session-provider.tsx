"use client";

import { createContext, useContext } from "react";

import type { Me, Organization } from "@/lib/api";

type SessionValue = Me & { activeOrganization: Organization };

const SessionContext = createContext<SessionValue | null>(null);

/**
 * The signed-in user and workspaces, loaded on the server in app/(app)/layout.tsx.
 * After a change (switch workspace, sign out) call router.refresh() to reload it.
 */
export function SessionProvider({ me, children }: { me: Me; children: React.ReactNode }) {
  const activeOrganization =
    me.organizations.find((o) => o.id === me.active_organization_id) ?? me.organizations[0]!;
  return (
    <SessionContext.Provider value={{ ...me, activeOrganization }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>.");
  return value;
}
