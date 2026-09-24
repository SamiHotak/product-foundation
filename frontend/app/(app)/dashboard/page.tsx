import type { Metadata } from "next";

import { JobsPanel } from "@/components/jobs/jobs-panel";
import { PageHeader } from "@/components/page-header";
import { SystemStatus } from "@/components/system-status";

export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Each product adds its own overview here. For now it shows whether every service is running, and lets you try a background job."
      />
      <div className="space-y-12">
        <SystemStatus />
        <JobsPanel />
      </div>
    </>
  );
}
