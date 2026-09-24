"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { product } from "@/config/product";
import { cn } from "@/lib/utils";

/** Sidebar navigation from config/product.ts. The current page gets an accent edge. */
export function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {product.nav.map(({ label, href, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative flex h-9 items-center gap-2.5 rounded-control px-3 text-sm transition-colors",
              active
                ? "bg-surface font-medium text-ink shadow-[0_1px_0_var(--line)]"
                : "text-ink-muted hover:bg-surface/60 hover:text-ink",
            )}
          >
            {active && (
              <span
                aria-hidden="true"
                className="absolute top-2 bottom-2 left-0 w-[3px] rounded-full bg-accent"
              />
            )}
            <Icon className={cn("size-4", active && "text-accent")} aria-hidden="true" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
