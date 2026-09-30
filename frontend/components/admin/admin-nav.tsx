"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const PAGES = [
  { label: "Overview", href: "/admin" },
  { label: "Workspaces", href: "/admin/workspaces" },
  { label: "Users", href: "/admin/users" },
  { label: "Subscriptions", href: "/admin/subscriptions" },
  { label: "AI usage", href: "/admin/usage" },
  { label: "Failed jobs", href: "/admin/jobs" },
];

/** Tabs of the admin area. */
export function AdminNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Admin" className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      <ul className="flex gap-1 border-b border-line">
        {PAGES.map(({ label, href }) => {
          const active = pathname === href;
          return (
            <li key={href} className="shrink-0">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative block px-3 py-2 text-sm whitespace-nowrap transition-colors",
                  active ? "font-medium text-ink" : "text-ink-muted hover:text-ink",
                )}
              >
                {label}
                {active && (
                  <span
                    aria-hidden="true"
                    className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-accent"
                  />
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
