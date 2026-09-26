import type { Metadata } from "next";

import { Section } from "@/components/settings/section";
import { ProfileSummary } from "@/components/settings/profile-summary";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <Section title="Profile" description="Changing your name and email arrives in a later update.">
      <ProfileSummary />
    </Section>
  );
}
