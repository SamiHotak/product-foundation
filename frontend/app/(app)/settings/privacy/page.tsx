import type { Metadata } from "next";

import { PrivacySettings } from "@/components/settings/privacy-settings";

export const metadata: Metadata = { title: "Privacy" };

export default function PrivacyPage() {
  return <PrivacySettings />;
}
