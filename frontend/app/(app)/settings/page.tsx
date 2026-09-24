import { UserRound } from "lucide-react";
import type { Metadata } from "next";

import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/ui/empty-state";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" description="Your profile, workspace, members and billing." />
      <EmptyState
        icon={UserRound}
        title="Settings need an account"
        description="Profile, workspace and member settings appear here after sign-in is added in phase 2. Theme can already be changed from the menu in the top right."
        className="max-w-2xl"
      />
    </>
  );
}
