import Link from "next/link";

import { MobileMenu } from "@/components/marketing/mobile-menu";
import { ProductMark } from "@/components/layout/product-mark";
import { Button } from "@/components/ui/button";
import { marketing } from "@/config/marketing";

/**
 * Top bar of the public website. Server-rendered; only the phone menu uses a little JavaScript.
 * `signedIn` only checks that a session cookie exists (no API call), so the page stays fast.
 * If the session expired, "Open the app" simply lands on the sign-in page.
 */
export function SiteHeader({ signedIn }: { signedIn: boolean }) {
  return (
    <header className="relative z-20">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4 sm:px-6">
        <ProductMark href="/" />
        <nav aria-label="Website" className="hidden flex-1 md:block">
          <ul className="flex items-center gap-1">
            {marketing.nav.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="rounded-control px-3 py-2 text-sm text-ink-muted transition-colors hover:text-ink"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="ml-auto hidden items-center gap-2 md:flex">
          {signedIn ? (
            <Button asChild>
              <Link href="/dashboard">Open the app</Link>
            </Button>
          ) : (
            <>
              <Button asChild variant="ghost">
                <Link href="/login">Sign in</Link>
              </Button>
              <Button asChild>
                <Link href="/signup">Create account</Link>
              </Button>
            </>
          )}
        </div>
        <MobileMenu signedIn={signedIn} />
      </div>
    </header>
  );
}
