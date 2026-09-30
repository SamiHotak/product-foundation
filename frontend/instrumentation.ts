/**
 * Runs once when the Next.js server starts (server-side error reports for Sentry).
 * Off unless NEXT_PUBLIC_SENTRY_DSN was set when the image was built, and then Sentry is only
 * loaded on demand: without a DSN this file does nothing and pulls in nothing.
 */
import type { Instrumentation } from "next";

import { sentryPrivacyOptions } from "@/lib/sentry-options";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

export async function register() {
  if (!dsn || process.env.NEXT_RUNTIME !== "nodejs") return;
  const Sentry = await import("@sentry/nextjs");
  Sentry.init({
    dsn,
    environment: process.env.NODE_ENV,
    release: process.env.NEXT_PUBLIC_SENTRY_RELEASE || undefined,
    ...sentryPrivacyOptions,
    // Errors only, no performance tracing: no OpenTelemetry and no module hooks, so Sentry adds
    // nothing to every request on the Node server.
    enableOpenTelemetrySetup: false,
    enableRuntimeChannelInjection: false,
  });
}

export const onRequestError: Instrumentation.onRequestError = async (...args) => {
  if (!dsn) return;
  const Sentry = await import("@sentry/nextjs");
  Sentry.captureRequestError(...args);
};
