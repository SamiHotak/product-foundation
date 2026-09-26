"use client";

import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { AuthHeader } from "@/components/auth/auth-header";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { api, errorMessage, unwrap } from "@/lib/api";

/**
 * Two states on one page:
 * - /verify-email?email=...  -> "check your inbox" (after sign-up), with "resend"
 * - /verify-email?token=...  -> confirms the email (from the link), signs in, opens the app
 */
export function VerifyEmail() {
  const params = useSearchParams();
  const token = params.get("token");
  return token ? <Confirming token={token} /> : <CheckInbox email={params.get("email") ?? ""} />;
}

function Confirming({ token }: { token: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false); // the link works once: never send it twice

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    unwrap(api.POST("/api/auth/verify-email", { body: { token } }))
      .then(() => {
        router.replace("/dashboard");
        router.refresh();
      })
      .catch((err: unknown) => setError(errorMessage(err)));
  }, [token, router]);

  if (!error) {
    return <AuthHeader title="Confirming your email…" description="One moment." />;
  }
  return (
    <>
      <AuthHeader title="This link didn't work" />
      <Alert tone="error">{error}</Alert>
      <p className="mt-4 text-sm text-ink-muted">
        Links work once and expire after 48 hours.{" "}
        <Link href="/login" className="font-medium text-accent hover:underline">
          Sign in
        </Link>{" "}
        to get a new one.
      </p>
    </>
  );
}

function CheckInbox({ email }: { email: string }) {
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  async function resend() {
    setState("sending");
    setError(null);
    try {
      await unwrap(api.POST("/api/auth/resend-verification", { body: { email } }));
      setState("sent");
    } catch (err) {
      setError(errorMessage(err));
      setState("idle");
    }
  }

  return (
    <>
      <MailCheck className="mb-4 size-8 text-accent" aria-hidden="true" />
      <AuthHeader
        title="Check your inbox"
        description={
          email ? (
            <>
              We sent a confirmation link to <strong className="text-ink">{email}</strong>. Open it
              to finish creating your account.
            </>
          ) : (
            "We sent you a confirmation link. Open it to finish creating your account."
          )
        }
      />
      {error && (
        <Alert tone="error" className="mb-4">
          {error}
        </Alert>
      )}
      {state === "sent" && (
        <Alert tone="success" className="mb-4">
          New link sent.
        </Alert>
      )}
      <div className="space-y-3 text-sm text-ink-muted">
        <p>Nothing after a few minutes? Check your spam folder.</p>
        {email && (
          <Button variant="secondary" onClick={() => void resend()} disabled={state === "sending"}>
            {state === "sending" ? "Sending…" : "Send the link again"}
          </Button>
        )}
      </div>
    </>
  );
}
