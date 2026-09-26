"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { api, ApiError, errorMessage, unwrap } from "@/lib/api";
import { safeNext } from "@/lib/safe-next";

const URL_ERRORS: Record<string, string> = {
  google: "Signing in with Google didn't work. Try again, or use your email.",
  google_disabled: "Google sign-in is not set up for this app yet.",
};

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState(""); // last submitted, for "send a new link"
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(URL_ERRORS[params.get("error") ?? ""] ?? null);
  const [unverified, setUnverified] = useState(false);
  const [resent, setResent] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Read from the form (not React state): text typed before the page finished loading is kept.
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "").trim();
    const password = String(form.get("password") ?? "");
    setEmail(email);
    if (!email || !password) {
      setError("Enter your email and password.");
      return;
    }
    setBusy(true);
    setError(null);
    setUnverified(false);
    try {
      await unwrap(api.POST("/api/auth/login", { body: { email, password } }));
      router.replace(safeNext(params.get("next")));
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError && err.code === "email_not_verified") setUnverified(true);
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  async function resend() {
    try {
      await unwrap(api.POST("/api/auth/resend-verification", { body: { email } }));
      setResent(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      {error && (
        <Alert tone="error">
          <p>{error}</p>
          {unverified && !resent && (
            <button type="button" onClick={() => void resend()} className="font-medium underline">
              Send a new confirmation link
            </button>
          )}
        </Alert>
      )}
      {resent && <Alert tone="success">New link sent. Check your inbox.</Alert>}
      <Field label="Email">
        {(a) => <Input {...a} type="email" autoComplete="email" required name="email" />}
      </Field>
      <Field
        label="Password"
        action={
          <Link href="/forgot-password" className="text-xs text-ink-muted hover:text-ink">
            Forgot password?
          </Link>
        }
      >
        {(a) => <PasswordInput {...a} autoComplete="current-password" required name="password" />}
      </Field>
      <Button type="submit" className="h-10 w-full" disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
