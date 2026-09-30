import type { Metadata } from "next";

import { AdminUsersView } from "@/components/admin/admin-users";

export const metadata: Metadata = { title: "Admin: Users" };

export default function Page() {
  return <AdminUsersView />;
}
