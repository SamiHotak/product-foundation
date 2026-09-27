import type { Metadata } from "next";

import { JobsPanel } from "@/components/jobs/jobs-panel";
import { OnboardingChecklist } from "@/components/onboarding/onboarding-checklist";
import { PageHeader } from "@/components/page-header";
import { SystemStatus } from "@/components/system-status";
import { getOnboarding } from "@/lib/api/server";

export const metadata: Metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  // Loaded on the server: a hidden checklist never flashes on screen.
  const onboarding = await getOnboarding();
  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Each product adds its own overview here. For now it shows whether every service is running, and lets you try a background job."
      />
      <div className="space-y-12">
        <OnboardingChecklist initial={onboarding} />
        <SystemStatus />
        <JobsPanel />
      </div>
    </>
  );
}
