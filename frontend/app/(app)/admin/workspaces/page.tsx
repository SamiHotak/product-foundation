import type { Metadata } from "next";

import { AdminWorkspacesView } from "@/components/admin/admin-workspaces";

export const metadata: Metadata = { title: "Admin: Workspaces" };

export default function Page() {
  return <AdminWorkspacesView />;
}
