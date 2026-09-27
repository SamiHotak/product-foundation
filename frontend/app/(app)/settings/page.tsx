import type { Metadata } from "next";

import { ProfileSettings } from "@/components/settings/profile-settings";

export const metadata: Metadata = { title: "Profile" };

export default function SettingsPage() {
  return <ProfileSettings />;
}
