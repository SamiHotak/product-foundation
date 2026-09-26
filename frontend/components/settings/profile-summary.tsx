"use client";

import { useSession } from "@/components/session-provider";

const ROLE_LABEL = { owner: "Owner", admin: "Admin", member: "Member" } as const;

/** Read-only for now. Editing the profile arrives in phase 3A. */
export function ProfileSummary() {
  const { user, activeOrganization } = useSession();
  const methods = [user.has_password && "Email and password", user.google_linked && "Google"]
    .filter(Boolean)
    .join(" · ");
  const rows: [string, string][] = [
    ["Name", user.name],
    ["Email", user.email],
    ["Sign-in methods", methods],
    ["Current workspace", activeOrganization.name],
    ["Your role", ROLE_LABEL[activeOrganization.role]],
  ];
  return (
    <dl className="divide-y divide-line rounded-menu border border-line">
      {rows.map(([label, value]) => (
        <div key={label} className="grid gap-1 px-4 py-3 text-sm sm:grid-cols-[12rem_1fr]">
          <dt className="text-ink-muted">{label}</dt>
          <dd className="min-w-0 truncate font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
