"use client";

import { useEffect } from "react";

/**
 * Last-resort error page: shown when the root layout itself fails. It replaces the whole
 * page, so it can't use our styles: plain inline style attributes only (never a <style> tag).
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    if (!process.env.NEXT_PUBLIC_SENTRY_DSN) return;
    void import("@sentry/nextjs").then((Sentry) => Sentry.captureException(error));
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          fontFamily: "system-ui, sans-serif",
          textAlign: "center",
          padding: "1.5rem",
        }}
      >
        <div>
          <h1 style={{ fontSize: "1.5rem", marginBottom: "0.5rem" }}>Something went wrong</h1>
          <p style={{ color: "#555", marginBottom: "1.25rem" }}>
            We have been told about it. Please try again.
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              padding: "0.6rem 1.1rem",
              borderRadius: "0.5rem",
              border: "1px solid #999",
              background: "transparent",
              cursor: "pointer",
              fontSize: "1rem",
            }}
          >
            Try again
          </button>
          {error.digest ? (
            <p style={{ color: "#777", fontSize: "0.8rem", marginTop: "1rem" }}>
              Reference: {error.digest}
            </p>
          ) : null}
        </div>
      </body>
    </html>
  );
}
