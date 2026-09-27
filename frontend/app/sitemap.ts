import type { MetadataRoute } from "next";

import { siteUrl } from "@/lib/site";

export const dynamic = "force-dynamic";

/** /sitemap.xml: the public pages. Add new marketing pages here. */
export default function sitemap(): MetadataRoute.Sitemap {
  const pages = [
    { path: "/", priority: 1 },
    { path: "/pricing", priority: 0.8 },
    { path: "/signup", priority: 0.5 },
    { path: "/login", priority: 0.3 },
    { path: "/legal/imprint", priority: 0.1 },
    { path: "/legal/privacy", priority: 0.1 },
    { path: "/legal/terms", priority: 0.1 },
    { path: "/legal/dpa", priority: 0.1 },
  ];
  return pages.map(({ path, priority }) => ({ url: `${siteUrl}${path}`, priority }));
}
