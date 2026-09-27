"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { marketing } from "@/config/marketing";

/**
 * Phone menu of the website: a native <details> element, so it opens even before JavaScript
 * loads. The script only closes it after a link is tapped or Escape is pressed.
 */
export function MobileMenu({ signedIn }: { signedIn: boolean }) {
  const ref = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && ref.current?.open) {
        ref.current.open = false;
        ref.current.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const closeOnLink = (event: React.MouseEvent) => {
    if ((event.target as HTMLElement).closest("a") && ref.current) ref.current.open = false;
  };

  return (
    <details ref={ref} className="group ml-auto md:hidden" onClick={closeOnLink}>
      <summary
        aria-label="Open menu"
        className="grid size-10 cursor-pointer list-none place-items-center rounded-control text-ink hover:bg-surface-sunken [&::-webkit-details-marker]:hidden"
      >
        <Menu className="size-5 group-open:hidden" aria-hidden="true" />
        <X className="hidden size-5 group-open:block" aria-hidden="true" />
      </summary>
      <div className="absolute inset-x-0 top-16 border-y border-line bg-surface px-4 pt-2 pb-5 shadow-[0_12px_24px_-12px_rgb(27_34_51/0.25)]">
        <nav aria-label="Website menu">
          <ul>
            {marketing.nav.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="block rounded-control px-2 py-3 text-base text-ink hover:bg-surface-sunken"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="mt-3 grid gap-2">
          {signedIn ? (
            <Button asChild className="h-11">
              <Link href="/dashboard">Open the app</Link>
            </Button>
          ) : (
            <>
              <Button asChild className="h-11">
                <Link href="/signup">Create account</Link>
              </Button>
              <Button asChild variant="secondary" className="h-11">
                <Link href="/login">Sign in</Link>
              </Button>
            </>
          )}
        </div>
      </div>
    </details>
  );
}
