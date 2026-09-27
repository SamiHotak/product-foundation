/**
 * Cookie-less website analytics.
 *
 *   track("signup", { plan: "pro" })     // a custom event, from any client component
 *
 * Page views are sent automatically by <Analytics /> (app/layout.tsx). Events go to our own
 * API (`POST /api/analytics/event`), which forwards them to Plausible or Umami when
 * ANALYTICS_PROVIDER is set on the backend (off by default). No script from another site,
 * no cookies, nothing stored in the browser.
 *
 * Privacy rules built in: only the PATH is sent (never ?query or #fragment, which can hold
 * tokens), only the ORIGIN of an outside referrer, and nothing at all when the browser asks
 * not to be tracked (Do Not Track / Global Privacy Control).
 */
import { api } from "@/lib/api";

type Props = Record<string, string>;

function optedOut(): boolean {
  const nav = navigator as Navigator & { globalPrivacyControl?: boolean };
  return nav.globalPrivacyControl === true || nav.doNotTrack === "1";
}

/** The referring site's origin, only if it is another site. */
function outsideReferrer(): string | undefined {
  try {
    const origin = new URL(document.referrer).origin;
    return origin !== window.location.origin ? origin : undefined;
  } catch {
    return undefined;
  }
}

function send(name: string, path: string, props?: Props, referrer?: string): void {
  if (optedOut()) return;
  // keepalive: the request survives when the visitor clicks a link right away.
  api
    .POST("/api/analytics/event", {
      body: { name, path: path.split(/[?#]/)[0] || "/", referrer, props },
      keepalive: true,
    })
    .catch(() => {
      // Statistics must never break the page.
    });
}

let lastPath: string | null = null;

/** Record a page view (called by <Analytics /> on every route change). */
export function trackPageview(path: string): void {
  if (path === lastPath) return; // React runs effects twice in development
  send("pageview", path, undefined, lastPath === null ? outsideReferrer() : undefined);
  lastPath = path;
}

/** Record a custom event, e.g. track("signup"). Names: lowercase letters, digits and _. */
export function track(name: string, props?: Props): void {
  send(name, window.location.pathname, props);
}
