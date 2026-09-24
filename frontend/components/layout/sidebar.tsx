import { NavLinks } from "@/components/layout/nav-links";
import { ProductMark } from "@/components/layout/product-mark";

/** Desktop sidebar (hidden on small screens; see MobileNav). */
export function Sidebar() {
  return (
    <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col gap-6 px-3 py-4 lg:flex">
      <ProductMark />
      <NavLinks />
    </aside>
  );
}
