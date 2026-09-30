import { notFound } from "next/navigation";

import { AdminNav } from "@/components/admin/admin-nav";
import { PageHeader } from "@/components/page-header";
import { getMe } from "@/lib/api/server";

/**
 * The app admin area. Only admins of the whole app (is_superuser, `make admin`) signed in
 * as themselves. Everyone else gets "page not found" (the API refuses them anyway).
 */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const me = await getMe();
  if (!me?.user.is_superuser || me.impersonator) notFound();
  return (
    <>
      <PageHeader
        title="Admin"
        description="All workspaces and users of this app, costs, failed jobs and the AI switch. Only app admins see this."
      />
      <div className="space-y-8">
        <AdminNav />
        <div className="min-w-0">{children}</div>
      </div>
    </>
  );
}
