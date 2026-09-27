/**
 * The public address of the website, e.g. https://askdocs.app (no slash at the end).
 * Used for links that must be absolute: social previews, sitemap.xml, robots.txt.
 * Set APP_URL for the frontend container (read when the server starts, not at build time).
 */
export const siteUrl = (process.env.APP_URL ?? "http://localhost:3000").replace(/\/+$/, "");
