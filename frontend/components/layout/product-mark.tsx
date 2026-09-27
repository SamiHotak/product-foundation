import Link from "next/link";

import { product } from "@/config/product";
import { cn } from "@/lib/utils";

/**
 * Logo + product name, from config/product.ts.
 * With a logo image: shows it (and its dark version in dark mode). Without: a monogram square.
 */
export function ProductMark({
  href = "/dashboard",
  size = "md",
}: {
  href?: string;
  size?: "md" | "lg";
}) {
  const { logo } = product;
  const showName = !logo?.wordmark;
  const box = size === "lg" ? "h-10" : "h-7";
  return (
    <Link
      href={href}
      aria-label={`${product.name} home`}
      className="inline-flex items-center gap-2.5 rounded-control px-1 py-1"
    >
      {logo ? (
        <>
          {/* Plain <img>: SVG logos need no optimisation, and this keeps the mark tiny. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={logo.src}
            alt=""
            width={logo.width}
            height={logo.height}
            className={cn(box, "w-auto", logo.darkSrc && "dark:hidden")}
          />
          {logo.darkSrc && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={logo.darkSrc}
              alt=""
              width={logo.width}
              height={logo.height}
              className={cn(box, "hidden w-auto dark:block")}
            />
          )}
        </>
      ) : (
        <span
          aria-hidden="true"
          className={cn(
            "grid place-items-center bg-accent font-bold text-accent-ink",
            size === "lg" ? "size-10 rounded-[9px] text-lg" : "size-7 rounded-[7px] text-[13px]",
          )}
        >
          {product.monogram}
        </span>
      )}
      {showName && (
        <span
          className={cn("font-semibold tracking-tight", size === "lg" ? "text-xl" : "text-[15px]")}
        >
          {product.name}
        </span>
      )}
    </Link>
  );
}
