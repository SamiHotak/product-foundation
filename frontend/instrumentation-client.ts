import { sentryPrivacyOptions } from "@/lib/sentry-options";

/**
 * Runs in the browser before the app starts (error reports for Sentry).
 * Off unless NEXT_PUBLIC_SENTRY_DSN was set when the image was built. When on, Sentry loads
 * AFTER the page has loaded and the browser is idle, so it never slows the first view (the
 * Lighthouse score). Reports go to /monitoring on OUR domain, which forwards them to Sentry:
 * the visitor's browser never talks to a third party.
 */
const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn && typeof window !== "undefined") {
  const start = () => {
    void import("@sentry/nextjs").then((Sentry) => {
      Sentry.init({
        dsn,
        tunnel: "/monitoring",
        environment: process.env.NODE_ENV,
        release: process.env.NEXT_PUBLIC_SENTRY_RELEASE || undefined,
        ...sentryPrivacyOptions,
      });
    });
  };
  const whenIdle = () =>
    "requestIdleCallback" in window ? window.requestIdleCallback(start) : setTimeout(start, 2000);
  if (document.readyState === "complete") whenIdle();
  else window.addEventListener("load", whenIdle, { once: true });
}
