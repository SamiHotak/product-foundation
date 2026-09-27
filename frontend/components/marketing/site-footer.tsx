import Link from "next/link";

import { ProductMark } from "@/components/layout/product-mark";
import { legal } from "@/config/legal";
import { marketing } from "@/config/marketing";
import { product } from "@/config/product";

export const LEGAL_LINKS = [
  { label: "Imprint", href: "/legal/imprint" },
  { label: "Privacy policy", href: "/legal/privacy" },
  { label: "Terms", href: "/legal/terms" },
  { label: "Data processing agreement", href: "/legal/dpa" },
];

/** Footer of the public website. The legal links must be reachable from every page (DDG §5). */
export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="border-t border-line">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-12 sm:px-6 md:grid-cols-[1fr_auto_auto] md:gap-16">
        <div className="space-y-3">
          <ProductMark href="/" />
          <p className="max-w-xs text-sm text-ink-muted">{product.tagline}</p>
        </div>
        <nav aria-label="Product">
          <h2 className="mb-3 text-sm font-semibold">Product</h2>
          <ul className="space-y-2 text-sm">
            {marketing.nav.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className="text-ink-muted hover:text-ink">
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <nav aria-label="Legal">
          <h2 className="mb-3 text-sm font-semibold">Legal</h2>
          <ul className="space-y-2 text-sm">
            {LEGAL_LINKS.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className="text-ink-muted hover:text-ink">
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
      <div className="mx-auto max-w-6xl px-4 pb-10 text-sm text-ink-muted sm:px-6">
        © {year} {legal.company.name}
      </div>
    </footer>
  );
}
