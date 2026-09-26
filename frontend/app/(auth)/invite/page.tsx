import type { Metadata } from "next";

import { InviteFlow } from "@/components/auth/invite-flow";
import { getInvitePreview, getMe, getProviders } from "@/lib/api/server";

export const metadata: Metadata = { title: "Join a workspace" };

/** Opened from the invite email: /invite?token=... Everything is loaded on the server. */
export default async function InvitePage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string | string[] }>;
}) {
  const raw = (await searchParams).token;
  const token = typeof raw === "string" ? raw : "";
  const [me, providers, invite] = await Promise.all([
    getMe(),
    getProviders(),
    getInvitePreview(token),
  ]);
  return (
    <InviteFlow
      token={token}
      me={me}
      googleEnabled={providers.google}
      preview={"preview" in invite ? invite.preview : null}
      error={"error" in invite ? invite.error : null}
    />
  );
}
