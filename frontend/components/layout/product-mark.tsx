import Link from "next/link";

import { product } from "@/config/product";

/** Logo square + product name. Phase 3 adds an optional logo image. */
export function ProductMark({ href = "/dashboard" }: { href?: string }) {
  return (
    <Link href={href} className="inline-flex items-center gap-2.5 rounded-control px-1 py-1">
      <span
        aria-hidden="true"
        className="grid size-7 place-items-center rounded-[7px] bg-accent text-[13px] font-bold text-accent-ink"
      >
        {product.monogram}
      </span>
      <span className="text-[15px] font-semibold tracking-tight">{product.name}</span>
    </Link>
  );
}
