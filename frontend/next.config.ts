import { withSentryConfig } from "@sentry/nextjs/config";
import type { NextConfig } from "next";

/**
 * The browser always calls the API on the same origin (`/api/...`).
 * Next.js forwards those calls to FastAPI. Same origin = no CORS problems,
 * and auth cookies (phase 2) stay first-party.
 *
 * API_INTERNAL_URL: where FastAPI lives, seen from the Next.js server.
 *   - Docker dev: http://backend:8000 (set in docker-compose.dev.yml)
 *   - Running `npm run dev` on Windows directly: http://localhost:8000 (default)
 */
const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

/**
 * Local development only: file uploads and downloads go to /storage/..., and Next.js
 * forwards them to the S3 container (SeaweedFS). The backend signs links for the S3
 * container's address; Next.js sends that host on, so the signatures still match.
 * In production this is unset: browsers talk to the object storage directly.
 */
const storageUrl = process.env.STORAGE_INTERNAL_URL;

/**
 * Sentry (error reports) is wired in ONLY when NEXT_PUBLIC_SENTRY_DSN is set while building
 * the image (production). Without it (dev, CI, tests) the config below is used untouched.
 */
const sentryDsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  // Dev server only: Playwright in Docker opens the app as http://frontend:3000
  // (make e2e, CI). Next.js blocks dev resources for unknown hosts by default.
  allowedDevOrigins: ["frontend"],
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiUrl}/api/:path*` },
      ...(storageUrl ? [{ source: "/storage/:path*", destination: `${storageUrl}/:path*` }] : []),
    ];
  },
};

export default sentryDsn
  ? withSentryConfig(nextConfig, {
      silent: true,
      telemetry: false,
      // Browsers send reports to /monitoring on our domain; Next.js forwards them to Sentry.
      tunnelRoute: "/monitoring",
      // No source map upload (it needs an auth token at build time). Add later if you want
      // readable browser stack traces.
      sourcemaps: { disable: true },
    })
  : nextConfig;
