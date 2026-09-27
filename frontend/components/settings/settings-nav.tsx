"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSession } from "@/components/session-provider";
import type { Permission } from "@/lib/api";
import { cn } from "@/lib/utils";

export type SettingsPage = {
  label: string;
  href: string;
  group: "Account" | "Workspace";
  needs?: Permission;
  /** Extra words for the command palette (Ctrl+K). */
  keywords?: string[];
};

/** Every settings page. The command palette lists them too. */
export const SETTINGS_PAGES: SettingsPage[] = [
  {
    label: "Profile",
    href: "/settings",
    group: "Account",
    keywords: ["name", "password", "theme"],
  },
  {
    label: "Privacy",
    href: "/settings/privacy",
    group: "Account",
    keywords: ["export", "delete", "gdpr", "download"],
  },
  {
    label: "Workspace",
    href: "/settings/workspace",
    group: "Workspace",
    keywords: ["organization", "rename", "leave"],
  },
  {
    label: "Members",
    href: "/settings/members",
    group: "Workspace",
    keywords: ["team", "invite", "roles", "people"],
  },
  {
    label: "Billing",
    href: "/settings/billing",
    group: "Workspace",
    needs: "billing:manage",
    keywords: ["plan", "invoice", "payment", "subscription"],
  },
  {
    label: "API keys",
    href: "/settings/api-keys",
    group: "Workspace",
    needs: "api_keys:manage",
    keywords: ["token", "integration"],
  },
  {
    label: "Audit log",
    href: "/settings/audit-log",
    group: "Workspace",
    needs: "audit:read",
    keywords: ["history", "activity", "security"],
  },
];

/** Settings sections. Pages you may not use are hidden (the API refuses them anyway). */
export function SettingsNav() {
  const pathname = usePathname();
  const { can } = useSession();
  const items = SETTINGS_PAGES.filter((item) => !item.needs || can(item.needs));
  return (
    <nav aria-label="Settings" className="-mx-4 overflow-x-auto px-4 lg:mx-0 lg:px-0">
      <ul className="flex gap-1 border-b border-line lg:flex-col lg:gap-0.5 lg:border-b-0">
        {items.map(({ label, href, group }, index) => {
          const active = pathname === href;
          const firstOfGroup = items[index - 1]?.group !== group;
          return (
            <li key={href} className="shrink-0">
              {firstOfGroup && (
                <p
                  aria-hidden="true"
                  className={cn(
                    "hidden px-3 pb-1 text-xs font-medium text-ink-muted/80 lg:block",
                    index > 0 && "pt-4",
                  )}
                >
                  {group}
                </p>
              )}
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
