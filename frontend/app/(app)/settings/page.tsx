import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { ProfileSummary } from "@/components/settings/profile-summary";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" description="Your account and workspace." />
      <ProfileSummary />
    </>
  );
}
