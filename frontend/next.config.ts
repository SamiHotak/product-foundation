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

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

export default nextConfig;
