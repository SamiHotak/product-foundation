/**
 * Server-side API calls (server components, layouts). They run inside the Next.js server,
 * so they call FastAPI directly and forward the browser's cookies.
 */
import "server-only";

import createClient from "openapi-fetch";
import { cookies } from "next/headers";

import { toApiError } from "./client";
import type { AuthProviders, InvitePreview, Me } from "./index";
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

/** What an invite link is for, or the message to show when it doesn't work. */
export async function getInvitePreview(
  token: string,
): Promise<{ preview: InvitePreview } | { error: string }> {
  if (!token) return { error: "This link is incomplete. Open it again from the email." };
  try {
    const { data, error, response } = await (
      await serverClient()
    ).POST("/api/invites/preview", { body: { token } });
    if (data) return { preview: data };
    return { error: toApiError(response.status, error).message };
  } catch {
    return { error: "Can't reach the server right now. Try again in a minute." };
  }
}
