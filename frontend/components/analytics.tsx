"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { trackPageview } from "@/lib/analytics";

/** Sends one cookie-less page view per page (see lib/analytics.ts). Renders nothing. */
export function Analytics() {
  const pathname = usePathname();
  useEffect(() => {
    if (pathname) trackPageview(pathname);
  }, [pathname]);
  return null;
}
