import { cookies } from "next/headers";

import { SiteFooter } from "@/components/marketing/site-footer";
import { SiteHeader } from "@/components/marketing/site-header";

/** Public website: landing page, pricing and legal pages. */
export default async function MarketingLayout({ children }: { children: React.ReactNode }) {
  // Only checks that a session cookie exists; no API call, so the website stays fast.
  const signedIn = (await cookies()).has("session");
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-control focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <SiteHeader signedIn={signedIn} />
      <main id="main" className="flex-1">
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
