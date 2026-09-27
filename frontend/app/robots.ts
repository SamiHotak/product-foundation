import type { MetadataRoute } from "next";

import { siteUrl } from "@/lib/site";

// Read APP_URL when the server runs, not at build time (one image, many domains).
export const dynamic = "force-dynamic";

/** /robots.txt: search engines may read the website, not the app or one-time links. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/api/", "/dashboard", "/settings", "/invite", "/verify-email", "/reset-password"],
    },
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}
