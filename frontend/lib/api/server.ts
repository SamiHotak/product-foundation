/**
 * Server-side API calls (server components, layouts). They run inside the Next.js server,
 * so they call FastAPI directly and forward the browser's cookies.
 */
import "server-only";

import createClient from "openapi-fetch";
import { cookies } from "next/headers";

import type { AuthProviders, Me } from "./index";
import type { paths } from "./schema";

const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

async function serverClient() {
  const cookieHeader = (await cookies()).toString();
  return createClient<paths>({
    baseUrl: apiUrl,
    headers: cookieHeader ? { cookie: cookieHeader } : {},
    cache: "no-store",
  });
}

/** The signed-in user, or null (not signed in, or the API is down). */
export async function getMe(): Promise<Me | null> {
  try {
    const { data } = await (await serverClient()).GET("/api/auth/me");
    return data ?? null;
  } catch {
    return null;
  }
}

/** Which sign-in buttons to show. Falls back to password only. */
export async function getProviders(): Promise<AuthProviders> {
  try {
    const { data } = await (await serverClient()).GET("/api/auth/providers");
    return data ?? { password: true, google: false };
  } catch {
    return { password: true, google: false };
  }
}
