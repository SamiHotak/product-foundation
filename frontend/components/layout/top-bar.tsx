import { MobileNav } from "@/components/layout/mobile-nav";
import { UserMenu } from "@/components/layout/user-menu";
import { WorkspaceSwitcher } from "@/components/layout/workspace-switcher";

/** Top bar inside the main sheet: menu (mobile), workspace switcher, user menu. */
export function TopBar() {
  return (
    <header className="flex h-14 items-center gap-2 border-b border-line px-3 sm:px-5">
      <MobileNav />
      <WorkspaceSwitcher />
      <div className="ml-auto flex items-center gap-2">
        <UserMenu />
      </div>
    </header>
  );
}
