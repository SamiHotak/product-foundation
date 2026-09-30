"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSession } from "@/components/session-provider";
import { product, type NavItem } from "@/config/product";
import { cn } from "@/lib/utils";

/** Is this menu item for this person? (Hidden only: the API checks every request itself.) */
export function canSee(
  item: NavItem,
  session: Pick<ReturnType<typeof useSession>, "can" | "user" | "impersonator">,
): boolean {
  if (item.needs && !session.can(item.needs)) return false;
  if (item.adminOnly && !(session.user.is_superuser && !session.impersonator)) return false;
  return true;
}

/** Is `href` the current page (or a page below it)? */
export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Sidebar links from config/product.ts. Items the person may not use are hidden. */
export function NavLinks({
  items = product.nav,
  label = "Main",
  onNavigate,
}: {
  items?: NavItem[];
  label?: string;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const session = useSession();
  return (
    <nav aria-label={label} className="flex flex-col gap-0.5">
      {items
        .filter((item) => canSee(item, session))
        .map(({ label: text, href, icon: Icon }) => {
          const active = isActive(pathname, href);
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
              {text}
            </Link>
          );
        })}
    </nav>
  );
}

/** Main navigation on top, footer items (Settings, Help, ...) pinned to the bottom. */
export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex flex-1 flex-col justify-between gap-6">
      <NavLinks onNavigate={onNavigate} />
      {product.navFooter.length > 0 && (
        <NavLinks items={product.navFooter} label="More" onNavigate={onNavigate} />
      )}
    </div>
  );
}
