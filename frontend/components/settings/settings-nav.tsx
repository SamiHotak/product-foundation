"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSession } from "@/components/session-provider";
import type { Permission } from "@/lib/api";
import { cn } from "@/lib/utils";

type Item = { label: string; href: string; needs?: Permission };

const ITEMS: Item[] = [
  { label: "Profile", href: "/settings" },
  { label: "Workspace", href: "/settings/workspace" },
  { label: "API keys", href: "/settings/api-keys", needs: "api_keys:manage" },
  { label: "Audit log", href: "/settings/audit-log", needs: "audit:read" },
  { label: "Privacy", href: "/settings/privacy" },
];

/** Settings sections. Pages you may not use are hidden (the API refuses them anyway). */
export function SettingsNav() {
  const pathname = usePathname();
  const { can } = useSession();
  const items = ITEMS.filter((item) => !item.needs || can(item.needs));
  return (
    <nav aria-label="Settings" className="-mx-4 overflow-x-auto px-4 lg:mx-0 lg:px-0">
      <ul className="flex gap-1 border-b border-line lg:flex-col lg:gap-0.5 lg:border-b-0">
        {items.map(({ label, href }) => {
          const active = pathname === href;
          return (
            <li key={href} className="shrink-0">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative block px-3 py-2 text-sm whitespace-nowrap transition-colors",
                  "lg:rounded-control",
                  active
                    ? "font-medium text-ink lg:bg-surface-sunken"
                    : "text-ink-muted hover:text-ink lg:hover:bg-surface-sunken/60",
                )}
              >
                {label}
                {active && (
                  <span
                    aria-hidden="true"
                    className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-accent lg:hidden"
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
