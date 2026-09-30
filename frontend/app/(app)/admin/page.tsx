import type { Metadata } from "next";

import { AdminOverviewView } from "@/components/admin/admin-overview";

export const metadata: Metadata = { title: "Admin: Overview" };

export default function Page() {
  return <AdminOverviewView />;
}
