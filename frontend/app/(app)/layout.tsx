import { redirect } from "next/navigation";

import { AppShell } from "@/components/layout/app-shell";
import { SessionProvider } from "@/components/session-provider";
import { getMe } from "@/lib/api/server";

/**
 * Everything under (app) needs a signed-in user. The check runs on the server,
 * so signed-out visitors never see a flash of the app.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const me = await getMe();
  if (!me) redirect("/login");
  return (
    <SessionProvider me={me}>
      {/* key: switching workspace remounts the page, so no data from the old one stays on screen */}
      <AppShell key={me.active_organization_id}>{children}</AppShell>
    </SessionProvider>
  );
}
