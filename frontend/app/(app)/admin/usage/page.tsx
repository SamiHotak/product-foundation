import type { Metadata } from "next";

import { AdminUsageView } from "@/components/admin/admin-usage";

export const metadata: Metadata = { title: "Admin: AI usage" };

export default function Page() {
  return <AdminUsageView />;
}
