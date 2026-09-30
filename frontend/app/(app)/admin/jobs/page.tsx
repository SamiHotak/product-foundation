import type { Metadata } from "next";

import { AdminJobsView } from "@/components/admin/admin-jobs";

export const metadata: Metadata = { title: "Admin: Failed jobs" };

export default function Page() {
  return <AdminJobsView />;
}
